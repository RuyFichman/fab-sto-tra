"""Risk Engine + Execution Engine (simulado).

Um único motor, passo a passo, usado tanto no backtest quanto no paper trading.
Sequência de cada pregão:
  0. virada de mês: IR sobre o ganho líquido do mês anterior sai do caixa;
     se `cash_cdi` > 0, o caixa parado rende essa fração do CDI do dia;
  1. abertura: posições com gap abaixo do stop saem na abertura (pior que o stop);
     saídas pendentes são executadas na abertura; papel sem negociar há
     DELIST_DAYS pregões é liquidado no último preço;
  2. abertura: entradas pendentes, dimensionadas pelo risco e pelos limites;
  3. intradiário: mínima <= stop executa no preço do stop;
  4. fechamento: marcação a mercado e fila de ordens para o pregão seguinte.
Só opera comprado e sem alavancagem (max_exposure <= 1).

Custo de execução por lado = taxas + meio spread fixo + impacto de mercado
(lei da raiz quadrada: y x volatilidade diária x raiz(valor da ordem / volume)).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

DELIST_DAYS = 10


@dataclass
class Position:
    ticker: str
    shares: int
    entry_date: str
    entry_price: float     # já com slippage
    stop: float
    cost: float            # desembolso total, incluindo taxas
    risk: float            # risco planejado em R$ (distância do stop x quantidade)
    days_held: int = 0
    adv: float = 0.0       # volume financeiro mediano na entrada
    vol: float = 0.0       # ATR / preço na entrada
    stale: int = 0         # pregões seguidos sem negociação


@dataclass
class State:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    pending_entries: list[tuple[str, float, float]] = field(default_factory=list)  # (ticker, atr, adv)
    pending_exits: dict[str, str] = field(default_factory=dict)                    # ticker -> motivo
    last_close: dict[str, float] = field(default_factory=dict)
    equity: float = 0.0
    peak_equity: float = 0.0
    halted: bool = False
    last_date: str | None = None
    tax_month: str | None = None
    month_pnl: float = 0.0
    month_sales: float = 0.0
    loss_carry: float = 0.0    # prejuízo acumulado a compensar (<= 0)
    taxes_paid: float = 0.0
    dividends: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        d = dict(d)
        d["positions"] = {k: Position(**v) for k, v in d["positions"].items()}
        d["pending_entries"] = [(*x, 0.0)[:3] for x in d["pending_entries"]]
        return cls(**d)


def _ok(x: float) -> bool:
    return x is not None and x == x and x > 0  # x == x descarta NaN


class Engine:
    def __init__(self, risk: dict, costs: dict, stop_mult: float, max_hold: int = 0,
                 state: State | None = None, halt_on_drawdown: bool = False, tax: dict | None = None):
        self.risk, self.stop_mult, self.max_hold = risk, stop_mult, max_hold
        self.fee = costs["fee_bps"] / 1e4
        self.slip = costs["slippage_bps"] / 1e4
        self.brokerage = costs["brokerage"]
        self.impact_y = costs.get("impact_y", 0.0)
        self.max_part = costs.get("max_participation", 0.0)
        self.halt_on_drawdown = halt_on_drawdown
        self.tax = tax if tax and tax.get("enabled") else None
        cap = risk["initial_capital"]
        self.state = state or State(cash=cap, equity=cap, peak_equity=cap)

    # ------------------------------------------------------------------ execução
    def _slippage(self, value: float, adv: float, vol: float) -> float:
        impact = self.impact_y * vol * math.sqrt(value / adv) if adv > 0 and vol > 0 else 0.0
        return self.slip + impact

    def _mark(self, px: dict[str, float]) -> float:
        s = self.state
        return s.cash + sum(
            p.shares * (px[t] if _ok(px.get(t)) else s.last_close.get(t, p.entry_price))
            for t, p in s.positions.items())

    def _sell(self, date: str, t: str, price: float, reason: str) -> dict:
        s = self.state
        p = s.positions.pop(t)
        fill = price * (1 - self._slippage(p.shares * price, p.adv, p.vol))
        proceeds = p.shares * fill * (1 - self.fee) - self.brokerage
        s.cash += proceeds
        pnl = proceeds - p.cost
        s.month_pnl += pnl
        s.month_sales += p.shares * fill
        return {"ticker": t, "entry_date": p.entry_date, "exit_date": date, "shares": p.shares,
                "entry_price": p.entry_price, "exit_price": fill, "pnl": pnl,
                "ret": pnl / p.cost, "r_multiple": pnl / p.risk if p.risk > 0 else 0.0,
                "days": p.days_held, "reason": reason}

    def _buy(self, date: str, t: str, open_px: float, atr: float, adv: float,
             equity: float, exposure: float) -> float:
        s, r = self.state, self.risk
        stop_dist = self.stop_mult * atr
        if not _ok(stop_dist) or stop_dist >= open_px:
            return 0.0
        ref = open_px * (1 + self.slip)
        limits = [
            equity * r["risk_per_trade"] / stop_dist,
            equity * r["max_position_pct"] / ref,
            (equity * r["max_exposure"] - exposure) / ref,
        ]
        if adv > 0 and self.max_part > 0:
            limits.append(adv * self.max_part / ref)
        lot = r["lot_size"]
        shares = math.floor(min(limits) / lot) * lot
        if shares <= 0:
            return 0.0
        vol = atr / open_px
        fill = open_px * (1 + self._slippage(shares * open_px, adv, vol))
        unit = fill * (1 + self.fee)
        shares = min(shares, math.floor((s.cash - self.brokerage) / unit / lot) * lot)
        if shares <= 0:
            return 0.0
        cost = shares * unit + self.brokerage
        s.cash -= cost
        s.positions[t] = Position(t, shares, date, fill, open_px - stop_dist, cost, shares * stop_dist,
                                  adv=adv, vol=vol)
        return shares * fill

    def _settle_tax(self, month: str) -> None:
        """IR de operações comuns: alíquota sobre o ganho líquido do mês, após
        compensar prejuízos; ganho isento se as vendas do mês ficarem no limite."""
        s, tx = self.state, self.tax
        if s.tax_month is not None and month != s.tax_month:
            exempt = s.month_pnl > 0 and s.month_sales <= tx["exempt_monthly_sales"]
            if not exempt:
                net = s.month_pnl + s.loss_carry
                if net > 0:
                    due = net * tx["rate"]
                    s.cash -= due
                    s.taxes_paid += due
                    s.loss_carry = 0.0
                else:
                    s.loss_carry = net
            s.month_pnl = s.month_sales = 0.0
        s.tax_month = month

    # --------------------------------------------------------- eventos societários
    def apply_split(self, t: str, ratio: float) -> None:
        """Desdobramento (ratio > 1) ou grupamento (ratio < 1) de uma posição."""
        p = self.state.positions.get(t)
        if p and ratio > 0 and ratio != 1:
            p.shares = math.floor(p.shares * ratio)
            p.entry_price /= ratio
            p.stop /= ratio
            if t in self.state.last_close:
                self.state.last_close[t] /= ratio

    def credit_dividend(self, t: str, per_share: float) -> float:
        p = self.state.positions.get(t)
        if not p or not per_share > 0:
            return 0.0
        amount = p.shares * per_share
        self.state.cash += amount
        self.state.dividends += amount
        return amount

    # --------------------------------------------------------------------- passo
    def step(self, date: str, o: dict, h: dict, l: dict, c: dict,
             entries: list[tuple], exits: set[str], allow_entries: bool = True,
             cdi: float = 0.0) -> list[dict]:
        """Processa um pregão. `entries` (ticker, atr[, adv]) e `exits` são os
        sinais do fechamento de `date`, que ficam na fila para o próximo passo.
        Retorna os trades fechados."""
        s = self.state
        closed: list[dict] = []
        if self.tax:
            self._settle_tax(date[:7])
        yield_pct = self.risk.get("cash_cdi", 0.0)  # caixa parado aplicado a uma fração do CDI
        if yield_pct and s.cash > 0 and cdi == cdi:
            s.cash *= 1 + cdi * yield_pct

        # 1. abertura: gaps contra o stop, saídas pendentes e papéis que sumiram
        for t in list(s.positions):
            p, op = s.positions[t], o.get(t)
            if not _ok(op):
                p.stale += 1  # sem negociação: ordem permanece pendente
                if p.stale >= DELIST_DAYS:
                    closed.append(self._sell(date, t, s.last_close.get(t, p.entry_price), "deslistado"))
                    s.pending_exits.pop(t, None)
                continue
            p.stale = 0
            if op <= p.stop:
                closed.append(self._sell(date, t, op, "stop_gap"))
                s.pending_exits.pop(t, None)
            elif t in s.pending_exits:
                closed.append(self._sell(date, t, op, s.pending_exits.pop(t)))

        # 2. abertura: entradas pendentes
        equity = self._mark(o)
        exposure = equity - s.cash
        for t, atr, adv in s.pending_entries:
            if t in s.positions or len(s.positions) >= self.risk["max_positions"]:
                continue
            if _ok(o.get(t)):
                exposure += self._buy(date, t, o[t], atr, adv, equity, exposure)
        s.pending_entries = []

        # 3. stops intradiários
        for t in list(s.positions):
            if _ok(l.get(t)) and l[t] <= s.positions[t].stop:
                closed.append(self._sell(date, t, s.positions[t].stop, "stop"))
                s.pending_exits.pop(t, None)

        # 4. fechamento
        for t, p in s.positions.items():
            if _ok(c.get(t)):
                s.last_close[t] = c[t]
                p.days_held += 1
        s.last_close = {t: v for t, v in s.last_close.items() if t in s.positions}
        s.equity = self._mark(c)
        s.peak_equity = max(s.peak_equity, s.equity)
        s.last_date = date
        if self.halt_on_drawdown:
            s.halted = bool(s.equity / s.peak_equity - 1 <= -self.risk["max_drawdown_halt"])

        # 5. fila para o próximo pregão
        for t, p in s.positions.items():
            if t in exits:
                s.pending_exits[t] = "regra"
            elif self.max_hold and p.days_held >= self.max_hold:
                s.pending_exits[t] = "tempo"
        if allow_entries and not s.halted:
            s.pending_entries = [(*e, 0.0)[:3] for e in entries if e[0] not in s.positions]
        return closed

    def exposure(self) -> float:
        return 1 - self.state.cash / self.state.equity if self.state.equity else 0.0

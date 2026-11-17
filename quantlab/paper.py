"""Paper trading: avança a conta simulada pregão a pregão, com estado persistente.

Nenhuma ordem real é enviada. As execuções usam os preços do dia sem ajuste de
dividendos. Na data ex, dividendos e JCP são creditados em caixa pelo valor
bruto (o JCP real tem 15% de IR na fonte) e desdobramentos ajustam quantidade,
preço de entrada e stop.
"""
from __future__ import annotations

import json
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .alerts import notify
from .backtest import TRADE_COLS, day_inputs
from .config import PAPER_DIR
from .data import build_dataset, download_cdi, load_panel, trading_days_between, universe_mask
from .engine import Engine, State
from .strategies import make_signals

STATE, TRADES, EQUITY, STATUS, KILL = (PAPER_DIR / n for n in
    ("state.json", "trades.csv", "equity.csv", "status.json", "KILL"))


def run_paper(cfg: dict, update: bool = True) -> dict:
    PAPER_DIR.mkdir(exist_ok=True)
    alerts: list[str] = []
    events: list[str] = []
    if update:
        try:
            build_dataset(cfg, cotahist_max_age_days=7)  # COTAHIST semanal; dias recentes vêm do Yahoo
        except (Exception, SystemExit) as e:  # sem dados novos: segue com o que há, sem novas entradas
            alerts.append(f"Falha ao atualizar dados ({type(e).__name__}: {e})")
        try:  # o CDI só entra nas métricas; a falha dele não trava a operação
            download_cdi(cfg)
        except Exception as e:
            alerts.append(f"CDI não atualizado ({type(e).__name__}); usando o último salvo")

    panel = load_panel(cfg)
    name = cfg["paper"]["strategy"]
    sig = make_signals(name, panel, universe_mask(panel, cfg), cfg["strategy"][name])

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    today = pd.Timestamp(now.date())
    # barra do dia só é confiável depois do fechamento
    last_valid = panel.dates[panel.dates < today][-1] if now.time() < time(18, 30) else panel.dates[-1]

    state = State.from_dict(json.loads(STATE.read_text())) if STATE.exists() else None
    eng = Engine({**cfg["risk"], **sig.risk}, cfg["costs"], sig.stop_mult, sig.max_hold, state,
                 halt_on_drawdown=True, tax=cfg.get("tax"))
    first = pd.Timestamp(eng.state.last_date) + pd.Timedelta(days=1) if eng.state.last_date \
        else pd.Timestamp(cfg["paper"]["start"])
    todo = panel.dates[(panel.dates >= first) & (panel.dates <= last_valid)]

    stale = trading_days_between(last_valid, today) > cfg["risk"]["max_stale_days"]
    if stale:
        alerts.append(f"Dados defasados: último pregão válido é {last_valid:%Y-%m-%d}")
    if KILL.exists():
        alerts.append("Kill switch manual ativo (arquivo paper/KILL)")
    block = stale or KILL.exists() or any(a.startswith("Falha") for a in alerts)

    tickers = panel.tickers
    trades, equity_rows = [], []
    for d in todo:
        row = lambda m: m.loc[d].to_numpy()
        ds = d.strftime("%Y-%m-%d")
        for t in list(eng.state.positions):
            ratio, div = panel.split.at[d, t], panel.dividend.at[d, t]
            if ratio > 0 and ratio != 1:
                eng.apply_split(t, ratio)
                events.append(f"{ds}: {t} desdobramento x{ratio:g}")
            paid = eng.credit_dividend(t, div)
            if paid:
                events.append(f"{ds}: {t} provento de R$ {paid:,.2f}")
        o, h, l, c = (dict(zip(tickers, row(getattr(panel, "raw_" + k)))) for k in ("open", "high", "low", "close"))
        for t in eng.state.positions:
            if not c[t] == c[t]:
                alerts.append(f"{ds}: {t} em carteira sem negociação")
        entries, exits = day_inputs(tickers, row(sig.entry), row(sig.exit), row(sig.atr), row(sig.rank), row(sig.adv))
        new = eng.step(ds, o, h, l, c, entries, exits, allow_entries=not (block and d == todo[-1]),
                       cdi=float(panel.cdi.get(d, 0.0)))
        events += [f"{ds}: {t['ticker']} encerrada ({t['reason']}), resultado R$ {t['pnl']:+,.2f}" for t in new]
        trades += new
        equity_rows.append({"date": ds, "equity": eng.state.equity, "exposure": eng.exposure()})

    s = eng.state
    if block:
        s.pending_entries = []
    if s.halted:
        alerts.append(f"Limite de drawdown atingido ({cfg['risk']['max_drawdown_halt']:.0%}): novas entradas bloqueadas")

    STATE.write_text(json.dumps(s.to_dict(), indent=2))
    if trades:
        pd.DataFrame(trades, columns=TRADE_COLS).to_csv(TRADES, mode="a", header=not TRADES.exists(), index=False)
    if equity_rows:
        pd.DataFrame(equity_rows).to_csv(EQUITY, mode="a", header=not EQUITY.exists(), index=False)

    ref = panel.raw_close.loc[last_valid]
    status = {
        "estrategia": name,
        "ultimo_pregao": s.last_date,
        "executado_em": now.isoformat(timespec="seconds"),
        "pregoes_processados": len(todo),
        "patrimonio": s.equity,
        "caixa": s.cash,
        "proventos_recebidos": s.dividends,
        "imposto_pago": s.taxes_paid,
        "novas_entradas_bloqueadas": bool(block or s.halted),
        "alertas": alerts,
        "eventos": events,
        "posicoes": [{"ticker": t, "qtd": p.shares, "entrada": p.entry_date, "preco_entrada": p.entry_price,
                      "stop": p.stop, "ultimo": s.last_close.get(t), "dias": p.days_held}
                     for t, p in s.positions.items()],
        "ordens_proximo_pregao": {
            "compras": [{"ticker": t, "ref_fechamento": float(ref[t]), "atr": a,
                         "stop_estimado": float(ref[t] - sig.stop_mult * a)} for t, a, _ in s.pending_entries],
            "vendas": [{"ticker": t, "motivo": m} for t, m in s.pending_exits.items()],
        },
    }
    o = status["ordens_proximo_pregao"]
    lines = alerts + events
    lines += [f"Vender {v['ticker']} ({v['motivo']})" for v in o["vendas"]]
    lines += [f"Comprar {c['ticker']}, stop ~{c['stop_estimado']:.2f}" for c in o["compras"]]
    if lines:  # dia sem novidade não gera notificação
        failed = notify(cfg, f"Quant Lab: paper até {s.last_date}", "\n".join(lines[:8]))
        status["alertas"] += [f"Alerta não enviado ({f})" for f in failed]
    STATUS.write_text(json.dumps(status, indent=2, ensure_ascii=False))
    return status

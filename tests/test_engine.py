import numpy as np
import pandas as pd
import pytest

from quantlab.data import Panel, infer_splits
from quantlab.engine import Engine, State
from quantlab.metrics import expected_max_sharpe, prob_sharpe
from quantlab.strategies import make_signals

RISK = {"initial_capital": 100_000.0, "risk_per_trade": 0.01, "max_position_pct": 0.5,
        "max_exposure": 1.0, "max_positions": 5, "lot_size": 1, "max_drawdown_halt": 0.2}
FREE = {"fee_bps": 0.0, "slippage_bps": 0.0, "brokerage": 0.0}


def bar(eng, date, o, h, l, c, entries=(), exits=()):
    px = lambda v: {"A": v}
    return eng.step(date, px(o), px(h), px(l), px(c), list(entries), set(exits))


def test_entry_fills_next_open_sized_by_risk():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    assert not eng.state.positions  # sinal no fechamento não executa no mesmo dia
    bar(eng, "d2", 20, 21, 19, 20)
    p = eng.state.positions["A"]
    assert p.entry_price == 20 and p.stop == 18
    assert p.shares == 500  # 1% de 100k / (2 x ATR 1.0)


def test_intraday_stop_fills_at_stop():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 20)
    (t,) = bar(eng, "d3", 20, 20, 17, 17.5)
    assert t["reason"] == "stop" and t["exit_price"] == 18
    assert t["r_multiple"] == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open_and_loses_more_than_planned():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 20)
    (t,) = bar(eng, "d3", 15, 16, 14, 15)
    assert t["reason"] == "stop_gap" and t["exit_price"] == 15
    assert t["r_multiple"] == pytest.approx(-2.5)


def test_rule_exit_next_open_and_costs_reduce_pnl():
    costs = {"fee_bps": 10.0, "slippage_bps": 10.0, "brokerage": 0.0}
    eng = Engine(RISK, costs, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 20, exits=["A"])
    (t,) = bar(eng, "d3", 20, 20, 20, 20)
    assert t["reason"] == "regra"
    assert t["ret"] == pytest.approx((0.999 * 0.999) / (1.001 * 1.001) - 1)
    assert eng.state.cash == pytest.approx(eng.state.equity)


def test_no_leverage_and_position_cap():
    risk = {**RISK, "risk_per_trade": 0.5, "max_position_pct": 0.3}
    eng = Engine(risk, FREE, stop_mult=2.0)
    o = {t: 10.0 for t in "ABCDE"}
    eng.step("d1", o, o, o, o, [(t, 0.1) for t in "ABCDE"], set())
    eng.step("d2", o, o, o, o, [], set())
    s = eng.state
    assert s.cash >= 0
    assert all(p.shares * 10 <= 30_000 for p in s.positions.values())
    assert sum(p.shares * 10 for p in s.positions.values()) <= 100_000


def test_state_roundtrip():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 20, exits=["A"])
    assert State.from_dict(eng.state.to_dict()) == eng.state


def _panel(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    mats = {}
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, (n, 3)), axis=0)),
                         index=idx, columns=list("ABC"))
    mats["close"] = close
    mats["open"] = close.shift().fillna(100) * (1 + rng.normal(0, 0.003, (n, 3)))
    mats["high"] = np.maximum(mats["open"], close) * 1.005
    mats["low"] = np.minimum(mats["open"], close) * 0.995
    raw = {f"raw_{k}": v for k, v in mats.items()}
    return Panel(**mats, **raw, turnover=close * 1e6, benchmark=close["A"], cdi=pd.Series(0.0, index=idx))


@pytest.mark.parametrize("name,params", [
    ("breakout", {"entry_lookback": 20, "exit_lookback": 10, "trend_sma": 50, "atr_window": 14, "atr_stop_mult": 2.0}),
    ("momentum", {"lookback": 120, "skip": 21, "top_k": 1, "exit_rank_mult": 2.0, "atr_window": 14, "atr_stop_mult": 5.0}),
    ("momentum", {"lookback": 120, "skip": 21, "top_k": 1, "exit_rank_mult": 2.0, "atr_window": 14,
                  "atr_stop_mult": 5.0, "abs_filter": True}),
    ("meanrev", {"trend_sma": 50, "rsi_window": 2, "rsi_entry": 10.0, "exit_sma": 5, "atr_window": 14, "atr_stop_mult": 3.0}),
])
def test_signals_have_no_lookahead(name, params):
    """Alterar o futuro não pode mudar nenhum sinal do passado."""
    p1, p2 = _panel(), _panel()
    cut = 300
    for k in ("open", "high", "low", "close"):
        getattr(p2, k).iloc[cut:] *= 3.0
    uni = pd.DataFrame(True, index=p1.dates, columns=p1.tickers)
    s1, s2 = make_signals(name, p1, uni, params), make_signals(name, p2, uni, params)
    assert s1.entry.iloc[:cut].any().any()
    for k in ("entry", "exit", "atr", "rank"):
        pd.testing.assert_frame_equal(getattr(s1, k).iloc[:cut], getattr(s2, k).iloc[:cut])


def test_market_impact_grows_with_order_size_and_participation_cap():
    costs = {**FREE, "impact_y": 1.0, "max_participation": 0.01}
    eng = Engine({**RISK, "max_position_pct": 1.0}, costs, stop_mult=2.0)
    o = {"A": 20.0, "B": 20.0}
    eng.step("d1", o, o, o, o, [("A", 1.0, 1e9), ("B", 1.0, 1e5)], set())
    eng.step("d2", o, o, o, o, [], set())
    a, b = eng.state.positions["A"], eng.state.positions["B"]
    assert b.shares == 50                    # 1% de R$ 100 mil de volume / R$ 20
    assert a.shares == 500 and a.entry_price > 20  # paga impacto acima da abertura
    assert a.entry_price == pytest.approx(20 * (1 + 0.05 * (10_000 / 1e9) ** 0.5))


def test_monthly_tax_with_loss_carry_and_exemption():
    tax = {"enabled": True, "rate": 0.15, "exempt_monthly_sales": 1000.0}
    eng = Engine({**RISK, "max_position_pct": 1.0}, FREE, stop_mult=2.0, tax=tax)

    def round_trip(month, buy, sell):
        bar(eng, f"{month}-01", buy, buy, buy, buy, entries=[("A", 1.0)])
        bar(eng, f"{month}-02", buy, buy, buy, buy, exits=["A"])
        return bar(eng, f"{month}-03", sell, sell, sell, sell)[0]["pnl"]

    loss = round_trip("2020-01", 20, 19)
    assert loss < 0
    bar(eng, "2020-02-01", 20, 20, 20, 20)
    assert eng.state.taxes_paid == 0 and eng.state.loss_carry == pytest.approx(loss)
    gain = round_trip("2020-03", 20, 24)
    cash = eng.state.cash
    bar(eng, "2020-04-01", 20, 20, 20, 20)
    assert eng.state.taxes_paid == pytest.approx(0.15 * (gain + loss))
    assert eng.state.cash == pytest.approx(cash - eng.state.taxes_paid)

    small = Engine({**RISK, "risk_per_trade": 0.0005}, FREE, stop_mult=2.0, tax=tax)
    bar(small, "2020-01-01", 20, 20, 20, 20, entries=[("A", 1.0)])
    bar(small, "2020-01-02", 20, 20, 20, 20, exits=["A"])
    bar(small, "2020-01-03", 24, 24, 24, 24)   # vende R$ 600: abaixo do limite de isenção
    bar(small, "2020-02-01", 20, 20, 20, 20)
    assert small.state.taxes_paid == 0


def test_split_and_dividend():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 20)
    equity, cash = eng.state.equity, eng.state.cash
    eng.apply_split("A", 2.0)
    p = eng.state.positions["A"]
    assert (p.shares, p.entry_price, p.stop) == (1000, 10, 9)
    bar(eng, "d3", 10, 10.5, 9.5, 10)          # preços já na escala nova: nada dispara
    assert "A" in eng.state.positions and eng.state.equity == pytest.approx(equity)
    assert eng.credit_dividend("A", 0.5) == 500 and eng.state.cash == cash + 500


def test_vanished_ticker_is_liquidated_at_last_price():
    eng = Engine(RISK, FREE, stop_mult=2.0)
    bar(eng, "d1", 10, 10, 10, 10, entries=[("A", 1.0)])
    bar(eng, "d2", 20, 21, 19, 21)
    nan = float("nan")
    closed = [t for i in range(10) for t in bar(eng, f"x{i}", nan, nan, nan, nan)]
    assert [t["reason"] for t in closed] == ["deslistado"] and closed[0]["exit_price"] == 21


def test_infer_splits_ignores_real_crash():
    idx = pd.bdate_range("2020-01-01", periods=60)
    close = pd.Series(40.0, index=idx)
    close.iloc[30:] = 10.0                       # 4:1
    df = pd.DataFrame({"close": close, "turnover": 1e6}, index=idx)
    factor, found = infer_splits(df)
    assert len(found) == 1 and factor.iloc[0] == 0.25 and factor.iloc[-1] == 1
    df.loc[idx[30], "turnover"] = 2e7            # mesmo salto com volume 20x: colapso real
    assert infer_splits(df)[1] == []


def test_deflated_sharpe_penalizes_many_trials():
    sr, n = 0.05, 2000                           # Sharpe diário ~0,8 ao ano
    assert prob_sharpe(sr, n, 0, 3) > 0.95
    assert expected_max_sharpe(1, 0.02) == 0
    few, many = expected_max_sharpe(5, 0.02), expected_max_sharpe(200, 0.02)
    assert 0 < few < many
    assert prob_sharpe(sr, n, 0, 3, many) < prob_sharpe(sr, n, 0, 3, few) < prob_sharpe(sr, n, 0, 3)


def test_idle_cash_earns_fraction_of_cdi():
    eng = Engine({**RISK, "cash_cdi": 0.8}, FREE, stop_mult=2.0)
    eng.step("d1", {}, {}, {}, {}, [], set(), cdi=0.001)
    assert eng.state.equity == pytest.approx(100_000 * 1.0008)
    plain = Engine(RISK, FREE, stop_mult=2.0)
    plain.step("d1", {}, {}, {}, {}, [], set(), cdi=0.001)
    assert plain.state.equity == 100_000


def test_pairs_has_no_lookahead_and_pays_costs():
    from quantlab import pairs

    cfg = {"costs": {"fee_bps": 3.0, "slippage_bps": 10.0}, "risk": {"initial_capital": 100_000.0}}
    p = {"formation": 120, "trading": 60, "n_pairs": 2, "entry_z": 1.0, "borrow_rate": 0.03}
    p1, p2 = _panel(), _panel()
    p2.close.iloc[330:] *= 3.0
    uni = pd.DataFrame(True, index=p1.dates, columns=p1.tickers)
    start = str(p1.dates[150].date())
    r1, r2 = pairs.run(p1, uni, cfg, p, start), pairs.run(p2, uni, cfg, p, start)
    cut = p1.dates[329]
    pd.testing.assert_series_equal(r1.equity[:cut], r2.equity[:cut])
    assert len(r1.trades) > 0
    free = pairs.run(p1, uni, {**cfg, "costs": {"fee_bps": 0.0, "slippage_bps": 0.0}}, {**p, "borrow_rate": 0.0}, start)
    assert free.equity.iloc[-1] > r1.equity.iloc[-1]

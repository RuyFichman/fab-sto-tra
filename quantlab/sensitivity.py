"""Teste de sensibilidade: a mesma hipótese sob condições perturbadas.

Uma vantagem real deve sobreviver a custos maiores, outro ponto de partida, um
universo um pouco diferente e um dia de atraso. Se o resultado depende de um
desses detalhes, provavelmente é ajuste aos dados. Não são hipóteses novas e
por isso não entram no registro.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .data import Panel, universe_mask
from .metrics import perf_stats, trade_stats
from .strategies import make_signals


def _row(group: str, label: str, res, cdi) -> dict:
    p, t = perf_stats(res.equity, cdi), trade_stats(res.trades, n_boot=200)
    return {"grupo": group, "cenario": label, "cagr": p["cagr"], "sharpe": p["sharpe"],
            "max_drawdown": p["max_drawdown"], "operacoes": t["operacoes"],
            "expectativa": t.get("expectativa", np.nan)}


def run(name: str, panel: Panel, cfg: dict, n_random: int = 10) -> pd.DataFrame:
    params = cfg["strategy"][name]
    start, end = cfg["periods"]["dev_start"], cfg["periods"]["dev_end"]
    uni = universe_mask(panel, cfg)
    sig = make_signals(name, panel, uni, params)
    rows = [_row("base", "configuração atual", run_backtest(panel, sig, cfg, start, end), panel.cdi)]

    for mult in (0, 2, 3):
        c = copy.deepcopy(cfg)
        c["costs"]["slippage_bps"] *= mult
        c["costs"]["fee_bps"] *= mult
        rows.append(_row("custos", f"taxas e spread x{mult}", run_backtest(panel, sig, c, start, end), panel.cdi))

    c = copy.deepcopy(cfg)
    c["tax"]["enabled"] = False
    rows.append(_row("imposto", "sem IR", run_backtest(panel, sig, c, start, end), panel.cdi))

    for year in range(pd.Timestamp(start).year + 1, pd.Timestamp(start).year + 4):
        rows.append(_row("início", f"começando em {year}",
                         run_backtest(panel, sig, cfg, f"{year}-01-01", end), panel.cdi))

    for n in (20, 30, 60):
        s = make_signals(name, panel, universe_mask(panel, cfg, top_n=n), params)
        rows.append(_row("universo", f"{n} mais líquidas", run_backtest(panel, s, cfg, start, end), panel.cdi))

    delayed = copy.copy(sig)
    for k in ("entry", "exit"):
        setattr(delayed, k, getattr(sig, k).shift(1, fill_value=False))
    for k in ("atr", "rank", "adv"):
        setattr(delayed, k, getattr(sig, k).shift(1))
    delayed.entry &= delayed.atr.notna() & delayed.rank.notna()
    rows.append(_row("execução", "um pregão de atraso", run_backtest(panel, delayed, cfg, start, end), panel.cdi))

    rng = np.random.default_rng(11)
    rand = []
    for _ in range(n_random):
        keep = pd.Series(rng.random(len(panel.tickers)) > 0.2, index=panel.tickers)
        s = copy.copy(sig)
        s.entry = sig.entry & keep
        rand.append(_row("", "", run_backtest(panel, s, cfg, start, end), panel.cdi))
    rand = pd.DataFrame(rand)
    for label, fn in (("pior", "min"), ("mediana", "median"), ("melhor", "max")):
        pick = rand.loc[(rand["sharpe"] - getattr(rand["sharpe"], fn)()).abs().idxmin()]
        rows.append({**pick, "grupo": "sem 20% dos papéis", "cenario": f"{label} de {n_random} sorteios"})
    return pd.DataFrame(rows).set_index(["grupo", "cenario"])

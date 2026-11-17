"""Arbitragem estatística entre pares, pelo método da distância (Gatev,
Goetzmann e Rouwenhorst, 2006).

A cada `trading` pregões: nos `formation` pregões anteriores, normaliza os
preços do universo e escolhe os `n_pairs` pares com menor soma dos quadrados
das diferenças. No período seguinte, quando a diferença de um par passa de
`entry_z` desvios, compra o que ficou para trás e vende a descoberto o outro,
em valores iguais; desfaz quando a diferença cruza zero ou a janela acaba.

É uma simulação SEPARADA do motor principal (que só opera comprado), mais
grosseira: fechamento a fechamento, com um pregão de espera entre o sinal e a
execução, custos por perna e aluguel sobre a ponta vendida, sem IR. Capital
comprometido: uma unidade por par, pares sem posição não rendem.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import TRADE_COLS, Result
from .data import Panel


def run(panel: Panel, universe: pd.DataFrame, cfg: dict, p: dict, start: str, end: str | None = None) -> Result:
    close = panel.close.ffill(limit=5)
    rets = close.pct_change()
    dates = panel.dates
    i0 = dates.searchsorted(pd.Timestamp(start))
    i1 = len(dates) if end is None else dates.searchsorted(pd.Timestamp(end), side="right")
    form_n, trade_n, n_pairs, z = p["formation"], p["trading"], p["n_pairs"], p["entry_z"]
    cost = 2 * (cfg["costs"]["fee_bps"] + cfg["costs"]["slippage_bps"]) / 1e4  # duas pernas
    borrow = p["borrow_rate"] / 252
    capital = cfg["risk"]["initial_capital"]
    port, active, trades = np.zeros(i1 - i0), np.zeros(i1 - i0), []

    for s in range(i0, i1, trade_n):
        if s < form_n + 1:
            continue
        eligible = universe.columns[universe.iloc[s - 1].to_numpy()]  # conhecido no fechamento anterior
        form = close.iloc[s - form_n:s][eligible].dropna(axis=1)
        norm = form / form.iloc[0]
        x = norm.to_numpy()
        gram = x.T @ x
        sq = np.diag(gram)
        ssd = sq[:, None] + sq[None, :] - 2 * gram
        iu = np.triu_indices(x.shape[1], 1)
        e = min(s + trade_n, i1)
        for k in np.argsort(ssd[iu])[:n_pairs]:
            a, b = norm.columns[iu[0][k]], norm.columns[iu[1][k]]
            sd = (norm[a] - norm[b]).std()
            spread = (close[a].iloc[s:e] / form[a].iloc[0] - close[b].iloc[s:e] / form[b].iloc[0]).to_numpy()
            state, sig = 0, np.zeros(len(spread))
            for t, v in enumerate(spread):
                if v != v:                       # uma perna parou de negociar
                    state = 0
                elif state == 0:
                    state = -1 if v > z * sd else 1 if v < -z * sd else 0
                elif (state == 1 and v >= 0) or (state == -1 and v <= 0):
                    state = 0
                sig[t] = state                   # +1: comprado em a, vendido em b
            held = np.zeros(len(sig))
            held[2:] = sig[:-2]                  # sinal em t, executa no fechamento de t+1
            diff = np.nan_to_num(rets[a].iloc[s:e].to_numpy()) - np.nan_to_num(rets[b].iloc[s:e].to_numpy())
            change = np.abs(np.diff(np.concatenate([[0.0], held, [0.0]])))
            daily = held * diff - change[:-1] * cost - (held != 0) * borrow
            daily[-1] -= change[-1] * cost       # desfaz o que estiver aberto no fim da janela
            port[s - i0:e - i0] += daily / n_pairs
            active[s - i0:e - i0] += (held != 0) / n_pairs
            edges = np.flatnonzero(change[:-1])
            for j, lo in enumerate(edges):
                if held[lo] == 0:
                    continue
                hi = edges[j + 1] if j + 1 < len(edges) else len(held)
                r = float(daily[lo:hi].sum() - (cost if hi < len(held) else 0.0))
                long, short = (a, b) if held[lo] > 0 else (b, a)
                trades.append({"ticker": f"{long}/{short}", "entry_date": f"{dates[s + lo]:%Y-%m-%d}",
                               "exit_date": f"{dates[s + hi - 1]:%Y-%m-%d}", "shares": 0,
                               "entry_price": np.nan, "exit_price": np.nan, "pnl": r * capital / n_pairs,
                               "ret": r, "r_multiple": 0.0, "days": int(hi - lo),
                               "reason": "convergiu" if hi < len(held) else "fim da janela"})

    idx = dates[i0:i1]
    return Result(equity=pd.Series(capital * np.cumprod(1 + port), index=idx, name="equity"),
                  exposure=pd.Series(active, index=idx, name="exposure"),
                  trades=pd.DataFrame(trades, columns=TRADE_COLS), open_positions=0)

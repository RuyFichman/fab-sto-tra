"""Validação walk-forward.

Para cada janela: escolhe-se a combinação de parâmetros com melhor Sharpe no
treino e usa-se APENAS o retorno dela no ano de teste seguinte. A curva fora da
amostra é a concatenação desses anos de teste.

Aproximação: cada combinação é simulada uma vez no período inteiro e os retornos
diários são recortados por janela (as posições não são zeradas nas fronteiras).
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .data import Panel
from .metrics import ANN
from .registry import log_trial
from .strategies import make_signals


def _sharpe(r: pd.Series, cdi: pd.Series) -> float:
    if len(r) < 20 or r.std() == 0:
        return -np.inf
    return float((r - cdi.reindex(r.index)).mean() / r.std() * np.sqrt(ANN))


def walk_forward(name: str, panel: Panel, universe: pd.DataFrame, cfg: dict) -> dict:
    grid = cfg["walkforward"]["grid"][name]
    keys = list(grid)
    start, end = cfg["periods"]["dev_start"], cfg["periods"]["dev_end"]
    returns: dict[str, pd.Series] = {}
    for values in product(*grid.values()):
        params = {**cfg["strategy"][name], **dict(zip(keys, values))}
        label = ", ".join(f"{k}={v}" for k, v in zip(keys, values))
        res = run_backtest(panel, make_signals(name, panel, universe, params), cfg, start, end)
        returns[label] = res.equity.pct_change().fillna(0.0)
        log_trial(name, params, "dev", "walkforward", returns[label], panel.cdi)
        print(f"  [{len(returns)}] {label}: Sharpe {_sharpe(returns[label], panel.cdi):+.2f}")

    rets = pd.DataFrame(returns)
    tr_y, te_y = cfg["walkforward"]["train_years"], cfg["walkforward"]["test_years"]
    y0, y1 = rets.index.year.min(), rets.index.year.max()
    oos, rows = [], []
    for y in range(y0 + tr_y, y1 + 1, te_y):
        train = rets[(rets.index.year >= y - tr_y) & (rets.index.year < y)]
        test = rets[(rets.index.year >= y) & (rets.index.year < y + te_y)]
        if test.empty:
            continue
        scores = train.apply(_sharpe, cdi=panel.cdi)
        best = scores.idxmax()
        oos.append(test[best])
        rows.append({"teste": f"{y}" if te_y == 1 else f"{y}-{y + te_y - 1}",
                     "parametros": best,
                     "sharpe_treino": scores[best],
                     "sharpe_teste": _sharpe(test[best], panel.cdi),
                     "retorno_teste": (1 + test[best]).prod() - 1})
    oos_r = pd.concat(oos)
    full = rets.apply(_sharpe, cdi=panel.cdi)
    return {
        "equity": (1 + oos_r).cumprod() * cfg["risk"]["initial_capital"],
        "windows": pd.DataFrame(rows).set_index("teste"),
        "combos": full.rename("sharpe_periodo_inteiro").to_frame(),
        "n_combos": len(returns),
    }

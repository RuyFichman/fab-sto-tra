"""Registro de hipóteses: toda configuração testada no período de desenvolvimento
fica anotada, para descontar do melhor resultado a sorte de ter tentado muitas.

Deflated Sharpe Ratio (DSR) = probabilidade de o Sharpe verdadeiro superar o
maior Sharpe que se esperaria por acaso entre N tentativas. Abaixo de ~95% não há
evidência de que o resultado seja mais do que sorte. Como as tentativas são
correlacionadas entre si, o N efetivo é menor e o DSR aqui é conservador.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import numpy as np
import pandas as pd

from .config import RESULTS_DIR
from .metrics import ANN, expected_max_sharpe, prob_sharpe, sharpe_moments

PATH = RESULTS_DIR / "hypotheses.csv"


def log_trial(strategy: str, params: dict, scope: str, origin: str,
              returns: pd.Series, cdi: pd.Series) -> None:
    blob = json.dumps(params, sort_keys=True, default=str)
    key = hashlib.sha1(f"{strategy}|{scope}|{blob}".encode()).hexdigest()[:12]
    m = sharpe_moments(returns, cdi)
    row = {"id": key, "quando": datetime.now().isoformat(timespec="seconds"), "estrategia": strategy,
           "escopo": scope, "origem": origin, "sharpe": m["sr"] * np.sqrt(ANN), **m, "parametros": blob}
    RESULTS_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(PATH) if PATH.exists() else pd.DataFrame()
    if len(df):
        df = df[df["id"] != key]
    pd.concat([df, pd.DataFrame([row])], ignore_index=True).to_csv(PATH, index=False)


def table() -> pd.DataFrame:
    """Tentativas em desenvolvimento, com PSR e DSR."""
    if not PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(PATH)
    dev = df[df["escopo"] == "dev"].copy()
    sr0 = expected_max_sharpe(len(dev), dev["sr"].std())
    dev["psr"] = [prob_sharpe(r.sr, r.n, r.skew, r.kurt) for r in dev.itertuples()]
    dev["dsr"] = [prob_sharpe(r.sr, r.n, r.skew, r.kurt, sr0) for r in dev.itertuples()]
    dev.attrs.update(n=len(dev), sharpe_acaso=sr0 * np.sqrt(ANN))
    return dev.sort_values("sharpe", ascending=False)[
        ["estrategia", "origem", "sharpe", "psr", "dsr", "parametros", "quando"]]

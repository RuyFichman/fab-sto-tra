"""Quant Lab: geração de sinais.

Convenção anti-look-ahead: o sinal da data t usa somente dados até o fechamento
de t e só é executado na abertura de t+1 (ver engine.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Panel, median_turnover


@dataclass
class Signals:
    entry: pd.DataFrame   # bool
    exit: pd.DataFrame    # bool
    atr: pd.DataFrame     # volatilidade para stop e dimensionamento
    rank: pd.DataFrame    # maior = prioridade quando há mais sinais que vagas
    stop_mult: float
    max_hold: int
    adv: pd.DataFrame     # volume financeiro mediano (impacto de mercado)
    risk: dict            # limites de risco específicos da estratégia


# ---------------------------------------------------------------------- indicadores

def atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ----------------------------------------------------------------------- estratégias

def _breakout(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c = df["close"]
    prior_high = df["high"].rolling(p["entry_lookback"]).max().shift()
    prior_low = df["low"].rolling(p["exit_lookback"]).min().shift()
    return pd.DataFrame({
        "entry": (c > prior_high) & (c > c.rolling(p["trend_sma"]).mean()),
        "exit": c < prior_low,
        "atr": atr(df, p["atr_window"]),
        "rank": c.pct_change(126),
    })


def _meanrev(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c = df["close"]
    r = rsi(c, p["rsi_window"])
    return pd.DataFrame({
        "entry": (c > c.rolling(p["trend_sma"]).mean()) & (r < p["rsi_entry"]),
        "exit": c > c.rolling(p["exit_sma"]).mean(),
        "atr": atr(df, p["atr_window"]),
        "rank": -r,
    })


STRATEGIES = {"breakout": _breakout, "meanrev": _meanrev}


def _momentum(panel: Panel, universe: pd.DataFrame, p: dict) -> dict[str, pd.DataFrame]:
    """Momentum relativo com rebalanceamento no primeiro pregão de cada mês
    (data conhecida no próprio dia, sem depender do calendário futuro)."""
    c = panel.close.ffill(limit=5)
    mom = (c.shift(p["skip"]) / c.shift(p["lookback"]) - 1).where(universe)
    weak = mom.isna()
    if p.get("abs_filter"):
        # momentum absoluto: o papel também precisa ter rendido mais que o CDI na mesma janela
        idx = (1 + panel.cdi).cumprod()
        hurdle = idx.shift(p["skip"]) / idx.shift(p["lookback"]) - 1
        weak |= mom.lt(hurdle, axis=0)
        mom = mom.where(~weak)
    rk = mom.rank(axis=1, ascending=False)
    months = pd.Series(panel.dates.to_period("M"), index=panel.dates)
    rebalance = months != months.shift()
    rebalance.iloc[0] = False
    return {"entry": (rk <= p["top_k"]).mul(rebalance, axis=0),
            "exit": ((rk > p["top_k"] * p["exit_rank_mult"]) | weak).mul(rebalance, axis=0),
            "rank": mom}


CROSS_SECTIONAL = {"momentum": _momentum}
ALL_STRATEGIES = [*STRATEGIES, *CROSS_SECTIONAL]


def make_signals(name: str, panel: Panel, universe: pd.DataFrame, params: dict) -> Signals:
    base = params.get("base", name)  # variantes reutilizam uma estratégia base
    xs = CROSS_SECTIONAL[base](panel, universe, params) if base in CROSS_SECTIONAL else None
    fn = (lambda df, p: pd.DataFrame({"atr": atr(df, p["atr_window"])})) if xs else STRATEGIES[base]
    out: dict[str, dict[str, pd.Series]] = {"entry": {}, "exit": {}, "atr": {}, "rank": {}}
    for t in panel.tickers:
        # indicadores calculados sobre os pregões em que o papel negociou
        df = pd.DataFrame({k: getattr(panel, k)[t] for k in ("open", "high", "low", "close")}).dropna()
        if df.empty:
            continue
        res = fn(df, params)
        for k in res:
            out[k][t] = res[k]

    def wide(k: str, fill=None) -> pd.DataFrame:
        m = pd.DataFrame(out[k]).reindex(index=panel.dates, columns=panel.tickers)
        return m if fill is None else m.fillna(fill).astype(bool)

    atr_m = wide("atr")
    if xs:
        rank_m, raw_entry, exit_m = xs["rank"], xs["entry"], xs["exit"]
    else:
        rank_m, raw_entry, exit_m = wide("rank"), wide("entry", False), wide("exit", False)
    entry = raw_entry & universe & atr_m.notna() & rank_m.notna()
    if params.get("regime_sma"):
        # filtro de regime: só abre posições com o benchmark acima da própria média
        b = panel.benchmark.reindex(panel.dates).ffill()
        entry = entry.mul(b > b.rolling(int(params["regime_sma"])).mean(), axis=0)
    return Signals(entry, exit_m, atr_m, rank_m,
                   float(params["atr_stop_mult"]), int(params.get("max_hold_days", 0)),
                   adv=median_turnover(panel, 60), risk=dict(params.get("risk", {})))

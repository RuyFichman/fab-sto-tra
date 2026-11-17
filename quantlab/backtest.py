from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Panel
from .engine import Engine, State
from .strategies import Signals

TRADE_COLS = ["ticker", "entry_date", "exit_date", "shares", "entry_price", "exit_price",
              "pnl", "ret", "r_multiple", "days", "reason"]


@dataclass
class Result:
    equity: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    open_positions: int
    taxes: float = 0.0


def day_inputs(tickers: list[str], entry_row, exit_row, atr_row, rank_row, adv_row):
    idx = np.flatnonzero(entry_row)
    idx = idx[np.argsort(-rank_row[idx], kind="stable")]
    entries = [(tickers[i], float(atr_row[i]), float(np.nan_to_num(adv_row[i]))) for i in idx]
    exits = {tickers[i] for i in np.flatnonzero(exit_row)}
    return entries, exits


def run_backtest(panel: Panel, sig: Signals, cfg: dict, start: str, end: str | None = None,
                 prices: str = "adjusted", engine: Engine | None = None) -> Result:
    """Simula de `start` a `end`. prices='adjusted' (backtest) ou 'raw' (paper)."""
    pre = "" if prices == "adjusted" else "raw_"
    sl = slice(pd.Timestamp(start), pd.Timestamp(end) if end else None)
    mats = [getattr(panel, pre + k).loc[sl].to_numpy() for k in ("open", "high", "low", "close")]
    ent, ext = sig.entry.loc[sl].to_numpy(), sig.exit.loc[sl].to_numpy()
    atr, rank, adv = (getattr(sig, k).loc[sl].to_numpy() for k in ("atr", "rank", "adv"))
    cdi = panel.cdi.loc[sl].to_numpy()
    dates, tickers = panel.dates[panel.dates.slice_indexer(sl.start, sl.stop)], panel.tickers

    eng = engine or Engine({**cfg["risk"], **sig.risk}, cfg["costs"], sig.stop_mult, sig.max_hold,
                           tax=cfg.get("tax"))
    equity, exposure, trades = [], [], []
    for i, d in enumerate(dates):
        o, h, l, c = (dict(zip(tickers, m[i])) for m in mats)
        entries, exits = day_inputs(tickers, ent[i], ext[i], atr[i], rank[i], adv[i])
        trades += eng.step(d.strftime("%Y-%m-%d"), o, h, l, c, entries, exits, cdi=cdi[i])
        equity.append(eng.state.equity)
        exposure.append(eng.exposure())
    return Result(
        equity=pd.Series(equity, index=dates, name="equity"),
        exposure=pd.Series(exposure, index=dates, name="exposure"),
        trades=pd.DataFrame(trades, columns=TRADE_COLS),
        open_positions=len(eng.state.positions),
        taxes=eng.state.taxes_paid,
    )

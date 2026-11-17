from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

ANN = 252
EULER = 0.5772156649


def perf_stats(equity: pd.Series, cdi: pd.Series, exposure: pd.Series | None = None,
               final_tax: float = 0.0) -> dict:
    """Métricas de uma curva de patrimônio. Sharpe/Sortino em excesso ao CDI.
    `final_tax`: alíquota sobre o ganho total, para comparar comprar-e-manter
    (que paga IR no resgate) com uma estratégia cuja curva já é líquida de IR."""
    r = equity.pct_change().dropna()
    if len(r) < 2:
        return {}
    years = len(r) / ANN
    ex = r - cdi.reindex(r.index).fillna(0.0)
    dd = equity / equity.cummax() - 1
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    downside = ex[ex < 0].std()
    out = {
        "retorno_total": equity.iloc[-1] / equity.iloc[0] - 1,
        "cagr": cagr,
        "volatilidade": r.std() * np.sqrt(ANN),
        "sharpe": ex.mean() / r.std() * np.sqrt(ANN) if r.std() > 0 else 0.0,
        "sortino": ex.mean() / downside * np.sqrt(ANN) if downside and downside > 0 else 0.0,
        "max_drawdown": dd.min(),
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else 0.0,
    }
    gain = out["retorno_total"]
    out["cagr_apos_ir"] = (1 + gain * (1 - final_tax if gain > 0 else 1)) ** (1 / years) - 1
    if exposure is not None:
        out["exposicao_media"] = float(exposure.mean())
    return out


def trade_stats(trades: pd.DataFrame, n_boot: int = 5000, seed: int = 7) -> dict:
    """Expectativa matemática: E = Pg*G - Pp*P (custos já embutidos no retorno)."""
    n = len(trades)
    if n == 0:
        return {"operacoes": 0}
    ret = trades["ret"].to_numpy()
    wins, losses = ret[ret > 0], ret[ret <= 0]
    pg = len(wins) / n
    g = wins.mean() if len(wins) else 0.0
    p = -losses.mean() if len(losses) else 0.0
    gross_win = trades.loc[trades.pnl > 0, "pnl"].sum()
    gross_loss = -trades.loc[trades.pnl <= 0, "pnl"].sum()
    rng = np.random.default_rng(seed)
    boot = rng.choice(ret, size=(n_boot, n), replace=True).mean(axis=1)
    se = ret.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {
        "operacoes": n,
        "taxa_acerto": pg,
        "ganho_medio": g,
        "perda_media": p,
        "payoff": g / p if p > 0 else np.nan,
        "expectativa": pg * g - (1 - pg) * p,
        "expectativa_ic95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "t_stat": ret.mean() / se if se and se > 0 else np.nan,
        "expectativa_R": trades["r_multiple"].mean(),
        "fator_lucro": gross_win / gross_loss if gross_loss > 0 else np.nan,
        "duracao_media": trades["days"].mean(),
        "lucro_liquido": trades["pnl"].sum(),
    }


def sharpe_moments(returns: pd.Series, cdi: pd.Series) -> dict:
    """Sharpe por período (não anualizado) e momentos, para PSR/DSR."""
    ex = (returns - cdi.reindex(returns.index).fillna(0.0)).dropna()
    sd = ex.std()
    return {"sr": float(ex.mean() / sd) if sd > 0 else 0.0, "n": int(len(ex)),
            "skew": float(ex.skew()), "kurt": float(ex.kurt() + 3)}


def prob_sharpe(sr: float, n: int, skew: float, kurt: float, sr_ref: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio (Bailey e López de Prado): probabilidade de o
    Sharpe verdadeiro superar `sr_ref`, dado o tamanho da amostra e as caudas."""
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if n < 3 or denom <= 0:
        return float("nan")
    return float(norm.cdf((sr - sr_ref) * np.sqrt(n - 1) / np.sqrt(denom)))


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """Maior Sharpe esperado por puro acaso entre `n_trials` tentativas sem valor."""
    if n_trials < 2 or not sr_std > 0:
        return 0.0
    return float(sr_std * ((1 - EULER) * norm.ppf(1 - 1 / n_trials)
                           + EULER * norm.ppf(1 - 1 / (n_trials * np.e))))


def yearly_returns(curves: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame({
        k: v.groupby(v.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1) for k, v in curves.items()
    })


def regime_table(equity: pd.Series, bench: pd.Series, lookback: int = 126, thr: float = 0.10) -> pd.DataFrame:
    """Retorno anualizado por regime do benchmark. O regime de cada dia é definido
    pelo retorno do benchmark nos `lookback` pregões ANTERIORES (sem olhar o dia)."""
    trail = bench.pct_change(lookback).shift().reindex(equity.index)
    regime = pd.Series(np.where(trail > thr, "alta", np.where(trail < -thr, "queda", "lateral")),
                       index=equity.index).where(trail.notna())
    r, rb = equity.pct_change(), bench.reindex(equity.index).pct_change()
    rows = []
    for name in ["alta", "lateral", "queda"]:
        m = regime == name
        if m.sum() < 5:
            continue
        rows.append({"regime": name, "pregoes": int(m.sum()),
                     "estrategia_aa": (1 + r[m].mean()) ** ANN - 1,
                     "benchmark_aa": (1 + rb[m].mean()) ** ANN - 1})
    return pd.DataFrame(rows).set_index("regime") if rows else pd.DataFrame()

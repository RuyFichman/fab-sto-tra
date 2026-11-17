"""Market Data: coleta, validação e montagem do painel de preços.

Fontes:
- COTAHIST (arquivos anuais oficiais da B3): preços e volumes de todos os papéis
  que já negociaram, inclusive os deslistados. É a fonte dos preços e define
  QUEM entra no universo em cada data, o que remove o viés de sobrevivência.
- Yahoo Finance (yfinance): usado só para os fatores de ajuste (dividendos e
  desdobramentos) e para os pregões mais recentes que o COTAHIST local ainda
  não tem. Os preços históricos do Yahoo têm barras erradas em ~2% dos dias.
- Banco Central (SGS 12): CDI diário.

Papéis que o Yahoo não cobre (deslistados) têm desdobramentos inferidos por
heurística e NÃO têm dividendos, o que subestima o retorno deles.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .config import DATA_DIR, RAW_DIR

OHLC = ["open", "high", "low", "close"]
JUMP_THRESHOLD = 0.40  # retorno diário ajustado acima disso é suspeito
COTA_DIR = DATA_DIR / "cotahist"
COTA_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
TICKER_RE = r"^[A-Z0-9]{4}(?:3|4|5|6|11)$"  # ON, PN e units
PARSER_MTIME = __import__("pathlib").Path(__file__).stat().st_mtime  # mudou o parser: refaz o cache
NICE_RATIOS = [2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 100, 200, 500, 1000]


# ------------------------------------------------------------------------- COTAHIST

def download_cotahist(cfg: dict, max_age_days: float = 0) -> None:
    """Baixa os arquivos anuais que faltam; anos encerrados ficam em cache e o
    ano corrente é rebaixado quando a cópia local passa de `max_age_days`."""
    import requests

    COTA_DIR.mkdir(parents=True, exist_ok=True)
    for year in range(pd.Timestamp(cfg["data"]["start"]).year, date.today().year + 1):
        path = COTA_DIR / f"COTAHIST_A{year}.ZIP"
        # completo se foi baixado depois do fim do ano a que se refere
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if mtime.year > year or (datetime.now() - mtime).total_seconds() < max_age_days * 86400:
                continue
        print(f"  COTAHIST {year}...", flush=True)
        r = requests.get(COTA_URL.format(year=year), timeout=600, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(path)


def parse_cotahist(zip_path) -> pd.DataFrame:
    """Lê o layout de largura fixa: mercado à vista (010), ações em lote padrão
    (BDI 02) e ETFs (BDI 14, só para o benchmark)."""
    with zipfile.ZipFile(zip_path) as z:
        buf = z.read(z.namelist()[0])
    start = buf.index(b"\n") + 1                 # pula o cabeçalho, cujo tamanho varia
    width = buf.index(b"\n", start) + 1 - start
    n = (len(buf) - start) // width
    a = np.frombuffer(buf, dtype=np.uint8, count=n * width, offset=start).reshape(n, width)
    if not (a[:, width - 1] == 10).all():
        # alguma linha fora do padrão desalinha a leitura em bloco: filtra linha a linha
        good = [ln for ln in buf.split(b"\n") if len(ln) == width - 1]
        a = np.frombuffer(b"".join(good), dtype=np.uint8).reshape(len(good), width - 1)
    is_ = lambda col, ch: a[:, col] == ord(ch)
    bdi = (is_(10, "0") & is_(11, "2")) | (is_(10, "1") & is_(11, "4"))
    a = a[is_(0, "0") & is_(1, "1") & bdi & is_(24, "0") & is_(25, "1") & is_(26, "0")]

    def num(lo: int, hi: int) -> np.ndarray:
        return (a[:, lo:hi].astype(np.int64) - 48) @ (10 ** np.arange(hi - lo - 1, -1, -1, dtype=np.int64))

    df = pd.DataFrame({
        "date": pd.to_datetime(num(2, 10).astype(str), format="%Y%m%d"),
        "etf": a[:, 10] == ord("1"),
        "ticker": np.char.strip(np.ascontiguousarray(a[:, 12:24]).view("S12").ravel().astype(str)),
        "open": num(56, 69) / 100, "high": num(69, 82) / 100, "low": num(82, 95) / 100,
        "close": num(108, 121) / 100, "volume": num(152, 170).astype(float), "turnover": num(170, 188) / 100,
    })
    return df[df["ticker"].str.match(TICKER_RE)].reset_index(drop=True)


def load_cotahist() -> pd.DataFrame:
    parts = []
    for z in sorted(COTA_DIR.glob("COTAHIST_A*.ZIP")):
        cache = z.with_suffix(".parquet")
        if not cache.exists() or cache.stat().st_mtime < max(z.stat().st_mtime, PARSER_MTIME):
            parse_cotahist(z).to_parquet(cache)
        parts.append(pd.read_parquet(cache))
    if not parts:
        raise SystemExit("Sem arquivos COTAHIST. Rode: python -m quantlab data")
    return pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"], ignore_index=True)


def infer_splits(df: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Fator de ajuste por desdobramentos/grupamentos inferidos do preço.

    Um salto entre fechamentos conta como desdobramento quando a razão fica a
    até 5% de uma proporção redonda E o volume financeiro do dia é normal. Em
    um colapso real o volume financeiro explode; em um desdobramento, não.
    """
    ratio = df["close"] / df["close"].shift()
    typical = df["turnover"].rolling(20, min_periods=5).median().shift()
    factor = pd.Series(1.0, index=df.index)
    found = []
    for d in ratio.index[(ratio > 1.8) | (ratio < 1 / 1.8)]:
        r = ratio[d]
        k = min(NICE_RATIOS, key=lambda c: abs(np.log((r if r > 1 else 1 / r) / c)))
        k = k if r > 1 else 1 / k
        if abs(np.log(r / k)) < 0.05 and df.at[d, "turnover"] < 4 * typical[d]:
            factor[df.index < d] *= k
            found.append(f"{d:%Y-%m-%d} x{k:g}")
    return factor, found


# --------------------------------------------------------------------------- Yahoo

def download_yahoo(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    names = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
             "Volume": "volume", "Dividends": "dividend", "Stock Splits": "split"}
    for i in range(0, len(tickers), 25):
        batch = tickers[i : i + 25]
        df = yf.download([f"{t}.SA" for t in batch], start=start, auto_adjust=False, actions=True,
                         group_by="ticker", threads=True, progress=False)
        for t in batch:
            try:
                sub = df[f"{t}.SA"].dropna(how="all", subset=["Close"])
            except KeyError:
                continue
            if sub.empty:
                continue
            sub = sub.rename(columns=names)
            for c in ("dividend", "split"):
                sub[c] = sub[c].fillna(0.0) if c in sub else 0.0
            sub = sub[OHLC + ["adj_close", "volume", "dividend", "split"]]
            sub.index = pd.to_datetime(sub.index).tz_localize(None)
            sub.index.name = "date"
            out[t] = sub
    return out


def yahoo_with_retry(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    out = download_yahoo(tickers, start)
    missing = [t for t in tickers if t not in out]
    if missing:  # falhas em lote costumam ser passageiras
        out.update(download_yahoo(missing, start))
    return out


def download_cdi(cfg: dict) -> pd.Series:
    """CDI diário (taxa ao dia, em fração) da API SGS do Banco Central."""
    import requests

    start = pd.Timestamp(cfg["data"]["start"]).date()
    end = date.today()
    parts = []
    while start <= end:  # a API limita séries diárias a janelas de 10 anos
        stop = min(start + timedelta(days=3650), end)
        url = (
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json"
            f"&dataInicial={start:%d/%m/%Y}&dataFinal={stop:%d/%m/%Y}"
        )
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        parts.append(pd.DataFrame(r.json()))
        start = stop + timedelta(days=1)
    df = pd.concat(parts)
    s = pd.Series(
        df["valor"].astype(float).values / 100.0,
        index=pd.to_datetime(df["data"], format="%d/%m/%Y"),
        name="cdi",
    )
    s = s[~s.index.duplicated()].sort_index()
    s.to_frame().to_parquet(DATA_DIR / "cdi.parquet")
    return s


# -------------------------------------------------------------------------- dataset

COLS = OHLC + ["adj_close", "volume", "turnover", "dividend", "split"]


def _clip_ret(close: pd.Series) -> pd.Series:
    return close.pct_change().clip(-0.2, 0.2)


def split_factor(raw_close: pd.Series, y_close: pd.Series) -> pd.Series:
    """S(d): razão entre o fechamento do Yahoo (ajustado por desdobramentos e
    bonificações) e o oficial. É uma função em degraus; a mediana móvel descarta
    as barras erradas do Yahoo e cada degrau recebe a mediana do seu trecho.
    Não depende do cadastro de eventos do Yahoo, que omite bonificações."""
    rho = (y_close / raw_close).dropna()
    med = rho.rolling(9, center=True, min_periods=1).median().to_numpy()
    seg = np.zeros(len(med), dtype=int)
    level = med[0]
    for i in range(1, len(med)):
        seg[i] = seg[i - 1]
        if abs(np.log(med[i] / level)) > 0.012:
            seg[i] += 1
            level = med[i]
    s = rho.groupby(seg).transform("median")
    recent = seg == seg[-1]
    if abs(s.iloc[-1] - 1) < 0.01:  # sem evento desde o último degrau: preços já coincidem
        s[recent] = 1.0
    return s


def adjust_with_yahoo(raw: pd.DataFrame, y: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Preços oficiais (como negociados) + fatores de ajuste do Yahoo.

    Preço ajustado = oficial x S x A, com S = desdobramentos (ver split_factor)
    e A = dividendos (adj_close / close do Yahoo). Devolve também a fração de
    dias em que oficial x S diverge mais de 2% do fechamento do Yahoo.
    """
    a_y = y["adj_close"] / y["close"]
    s_common = split_factor(raw["close"], y["close"])
    s_y = s_common.reindex(y.index).ffill().bfill()
    tail = y[y.index > raw.index[-1]]  # pregões recentes que o COTAHIST local ainda não tem
    ratio = y["split"].where(y["split"] > 0, 1.0)  # eventos dentro da cauda, do cadastro do Yahoo
    s_tail = (1 / ratio)[::-1].cumprod()[::-1].shift(-1).fillna(1.0)[tail.index]
    tail_raw = tail[OHLC].div(s_tail, axis=0)
    tail_raw["volume"] = tail["volume"] * s_tail
    tail_raw["turnover"] = tail["close"] * tail["volume"]
    full = pd.concat([raw[OHLC + ["volume", "turnover"]], tail_raw])
    s = pd.concat([s_common.reindex(raw.index).ffill().bfill() * (s_tail.iloc[0] if len(tail) else 1.0), s_tail])
    a = a_y.reindex(full.index).ffill().bfill()
    mismatch = float(((raw["close"] * s[raw.index] / y["close"].reindex(raw.index) - 1).abs() > 0.02).mean())
    full["adj_close"] = full["close"] * s * a
    full["dividend"] = (y["dividend"] / s_y).reindex(full.index).fillna(0.0)
    full["split"] = y["split"].reindex(full.index).fillna(0.0)
    return full[COLS], mismatch


def adjust_heuristic(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    factor, splits = infer_splits(raw)
    out = raw[OHLC + ["volume", "turnover"]].copy()
    out["adj_close"] = out["close"] * factor
    out["dividend"], out["split"] = 0.0, 0.0
    return out[COLS], splits


def build_dataset(cfg: dict, cotahist_max_age_days: float = 0) -> pd.DataFrame:
    """Monta data/raw/ com todo papel que já esteve entre os mais líquidos."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    download_cotahist(cfg, cotahist_max_age_days)
    cota = load_cotahist()
    cota = cota[cota["date"] >= cfg["data"]["start"]].drop_duplicates(["ticker", "date"])
    bench = cfg["data"]["benchmark"]
    stocks = cota[~cota["etf"]]
    by_ticker = {t: d.set_index("date") for t, d in cota[~cota["etf"] | (cota["ticker"] == bench)].groupby("ticker")}
    first = pd.Series({t: d.index[0] for t, d in by_ticker.items()})
    last = pd.Series({t: d.index[-1] for t, d in by_ticker.items()})
    calendar = by_ticker[bench].index

    u = cfg["universe"]
    turn = stocks.pivot(index="date", columns="ticker", values="turnover")
    liq = turn.rolling(u["liquidity_window"], min_periods=u["liquidity_window"] // 2).median()
    ever = (liq.rank(axis=1, ascending=False) <= u["candidate_top_n"]).any()
    candidates = sorted(ever.index[ever])
    active = [t for t in candidates if last[t] >= calendar[-6]]

    print(f"  {len(candidates)} candidatas ({len(active)} ativas). Baixando fatores de ajuste (Yahoo)...", flush=True)
    yahoo = yahoo_with_retry(active + [bench], cfg["data"]["start"])
    if bench not in yahoo:
        raise SystemExit(f"Yahoo não retornou o benchmark {bench}; dados anteriores mantidos.")

    frames: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict] = {}
    absorbed: set[str] = set()
    for t, y in yahoo.items():
        raw, chain = by_ticker[t], []
        # o Yahoo republica o histórico de um papel renomeado sob o código novo:
        # emenda os preços oficiais do código antigo, que termina onde o novo começa
        while y.index[0] < raw.index[0] - pd.Timedelta(days=30):
            start = raw.index[0]
            near = last.index[(last >= start - pd.Timedelta(days=20)) & (last <= start + pd.Timedelta(days=3))
                              & (first < start - pd.Timedelta(days=90))]
            yr = _clip_ret(y["close"][y.index < start]).tail(750)
            corr = pd.Series({x: yr.corr(_clip_ret(by_ticker[x]["close"]), min_periods=60)
                              for x in near if x not in yahoo and x not in absorbed}, dtype=float)
            if corr.empty or not corr.max() > 0.9:
                break
            pred = corr.idxmax()
            raw = pd.concat([by_ticker[pred][by_ticker[pred].index < start], raw])
            absorbed.add(pred)
            chain.append(pred)
        df, mismatch = adjust_with_yahoo(raw, y)
        row = {"fonte": "cotahist+yahoo", "ativo": True, "historico_de": ", ".join(chain),
               "divergencia_yahoo": round(mismatch, 3)}
        if mismatch > 0.10:
            df2, splits = adjust_heuristic(raw)
            df = pd.concat([df2, df[df.index > raw.index[-1]]])
            row.update(fonte="cotahist", desdobramentos_inferidos="; ".join(splits),
                       obs="fatores do Yahoo incoerentes com os preços oficiais; sem dividendos")
        frames[t], meta[t] = df, row
    for t in candidates:
        if t in frames:
            continue
        if t in absorbed:
            continue
        frames[t], splits = adjust_heuristic(by_ticker[t])
        meta[t] = {"fonte": "cotahist", "ativo": t in active, "desdobramentos_inferidos": "; ".join(splits)}

    for old in RAW_DIR.glob("*.parquet"):
        old.unlink()
    for t, d in frames.items():
        d.index.name = "date"
        d.to_parquet(RAW_DIR / f"{t}.parquet")
    m = pd.DataFrame.from_dict(meta, orient="index").rename_axis("ticker").sort_index()
    m.to_csv(DATA_DIR / "universe_meta.csv")
    return m


# ------------------------------------------------------------------------ validação

def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove barras inválidas e devolve estatísticas de qualidade."""
    n0 = len(df)
    df = df[~df.index.duplicated()].sort_index()
    dup = n0 - len(df)
    bad_price = df[OHLC + ["adj_close"]].isna().any(axis=1) | (df[OHLC] <= 0).any(axis=1)
    no_volume = ~bad_price & ~(df["volume"] > 0)
    df = df[~bad_price & ~no_volume].copy()
    hi = df[["open", "close", "high"]].max(axis=1)
    lo = df[["open", "close", "low"]].min(axis=1)
    inconsistent = int(((hi > df["high"]) | (lo < df["low"])).sum())
    df["high"], df["low"] = hi, lo
    for c in ("dividend", "split"):
        if c not in df:
            df[c] = 0.0
    jumps = df["adj_close"].pct_change().abs() > JUMP_THRESHOLD
    stats = {
        "barras": len(df),
        "inicio": df.index.min().date() if len(df) else None,
        "fim": df.index.max().date() if len(df) else None,
        "duplicadas": dup,
        "preco_invalido": int(bad_price.sum()),
        "sem_volume": int(no_volume.sum()),
        "ohlc_inconsistente": inconsistent,
        "saltos_suspeitos": int(jumps.sum()),
        "datas_saltos": ", ".join(d.strftime("%Y-%m-%d") for d in df.index[jumps][:5]),
    }
    return df, stats


def validation_report() -> pd.DataFrame:
    rows = []
    for p in sorted(RAW_DIR.glob("*.parquet")):
        _, stats = clean(pd.read_parquet(p))
        rows.append({"ticker": p.stem, **stats})
    rep = pd.DataFrame(rows).set_index("ticker")
    meta_path = DATA_DIR / "universe_meta.csv"
    if meta_path.exists():
        rep = rep.join(pd.read_csv(meta_path, index_col=0), how="outer")
    rep.to_csv(DATA_DIR / "validation_report.csv")
    return rep


# --------------------------------------------------------------------------- painel

@dataclass
class Panel:
    """Matrizes datas x tickers. OHLC ajustado por proventos; raw_* sem ajuste."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    raw_open: pd.DataFrame
    raw_high: pd.DataFrame
    raw_low: pd.DataFrame
    raw_close: pd.DataFrame
    turnover: pd.DataFrame  # volume financeiro (R$)
    benchmark: pd.Series    # fechamento ajustado do benchmark
    cdi: pd.Series          # taxa diária
    dividend: pd.DataFrame | None = None  # R$ por ação na data ex
    split: pd.DataFrame | None = None     # proporção na data do desdobramento

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)


def load_panel(cfg: dict) -> Panel:
    bench = cfg["data"]["benchmark"]
    frames: dict[str, pd.DataFrame] = {}
    for p in sorted(RAW_DIR.glob("*.parquet")):
        frames[p.stem], _ = clean(pd.read_parquet(p))
    if bench not in frames:
        raise SystemExit("Sem dados. Rode primeiro: python -m quantlab data")
    calendar = frames[bench].index
    keys = ["open", "high", "low", "close", "raw_open", "raw_high", "raw_low", "raw_close",
            "turnover", "dividend", "split"]
    cols: dict[str, dict[str, pd.Series]] = {k: {} for k in keys}
    for t, df in frames.items():
        if t == bench:
            continue
        f = df["adj_close"] / df["close"]
        for c in OHLC:
            cols[c][t] = df[c] * f
            cols[f"raw_{c}"][t] = df[c]
        cols["turnover"][t] = df["turnover"]
        cols["dividend"][t], cols["split"][t] = df["dividend"], df["split"]
    mats = {k: pd.DataFrame(v).reindex(calendar) for k, v in cols.items()}
    mats["dividend"], mats["split"] = mats["dividend"].fillna(0.0), mats["split"].fillna(0.0)
    cdi_path = DATA_DIR / "cdi.parquet"
    if cdi_path.exists():
        cdi = pd.read_parquet(cdi_path)["cdi"].reindex(calendar).fillna(0.0)
    else:
        print("AVISO: CDI indisponível; Sharpe será calculado com taxa livre de risco zero.")
        cdi = pd.Series(0.0, index=calendar)
    return Panel(benchmark=frames[bench]["adj_close"], cdi=cdi, **mats)


def median_turnover(panel: Panel, window: int) -> pd.DataFrame:
    """Mediana do volume financeiro nos últimos `window` pregões negociados."""
    return pd.DataFrame(
        {t: panel.turnover[t].dropna().rolling(window).median() for t in panel.tickers}
    ).reindex(panel.dates).ffill(limit=5)


def universe_mask(panel: Panel, cfg: dict, top_n: int | None = None) -> pd.DataFrame:
    """Top-N por liquidez usando apenas informação disponível até cada data."""
    u = cfg["universe"]
    seasoned = panel.close.notna().cumsum() >= u["min_history"]
    liq = median_turnover(panel, u["liquidity_window"]).where(seasoned)
    return (liq.rank(axis=1, ascending=False) <= (top_n or u["top_n"])).fillna(False)


def trading_days_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return int(np.busday_count(a.date(), b.date()))

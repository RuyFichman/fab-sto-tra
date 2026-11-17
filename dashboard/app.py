"""Dashboard pessoal. Rodar com:  streamlit run dashboard/app.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RESULTS, PAPER, DATA = ROOT / "results", ROOT / "paper", ROOT / "data"

st.set_page_config(page_title="Quant Lab", layout="wide")

try:
    DARK = st.context.theme.type == "dark"
except Exception:
    DARK = st.get_option("theme.base") == "dark"

# paleta categórica em ordem fixa: a cor segue a série, nunca a posição
SERIES = {
    "estrategia": ("Estratégia", "#3987e5" if DARK else "#2a78d6"),
    "benchmark": ("BOVA11 (comprar e manter)", "#d95926" if DARK else "#eb6834"),
    "cdi": ("CDI", "#199e70" if DARK else "#1baf7a"),
}
INK = "#c3c2b7" if DARK else "#52514e"
GRID = "#2c2c2a" if DARK else "#e1e0d9"
AXIS = "#383835" if DARK else "#c3c2b7"
GOOD, BAD = ("#3987e5", "#e66767") if DARK else ("#2a78d6", "#e34948")


def layout(fig: go.Figure, title: str, height: int = 380, **kw) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)), height=height,
        margin=dict(l=10, r=10, t=48, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK),
        hovermode="x unified", legend=dict(orientation="h", y=1.0, yanchor="bottom", x=1, xanchor="right"),
        **kw)
    fig.update_xaxes(showgrid=False, linecolor=AXIS)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def line_chart(curves: pd.DataFrame, title: str, fmt: str, cols=("estrategia", "benchmark", "cdi")) -> go.Figure:
    fig = go.Figure()
    for c in cols:
        name, color = SERIES[c]
        fig.add_trace(go.Scatter(x=curves.index, y=curves[c], name=name, mode="lines",
                                 line=dict(color=color, width=2), hovertemplate=f"%{{y:{fmt}}}"))
    return layout(fig, title)


pct = lambda v, d=1: "–" if v is None or pd.isna(v) else f"{v:+.{d}%}"
num = lambda v: "–" if v is None or pd.isna(v) else f"{v:.2f}"


def perf_table(perf: dict) -> pd.DataFrame:
    rows = {"Retorno total": ("retorno_total", pct), "Retorno anual (CAGR)": ("cagr", pct),
            "Retorno anual após IR": ("cagr_apos_ir", pct),
            "Volatilidade anual": ("volatilidade", pct), "Sharpe (excesso ao CDI)": ("sharpe", num),
            "Drawdown máximo": ("max_drawdown", pct), "Calmar": ("calmar", num)}
    return pd.DataFrame({SERIES[k][0]: {label: f(perf[k].get(key)) for label, (key, f) in rows.items()}
                         for k in ("estrategia", "benchmark", "cdi")})


# ------------------------------------------------------------------------- páginas

def page_backtest(folder: Path) -> None:
    stats = json.loads((folder / "stats.json").read_text(encoding="utf-8"))
    curves = pd.read_parquet(folder / "curves.parquet")
    perf, ops = stats["desempenho"], stats.get("operacoes", {})
    s, b = perf["estrategia"], perf["benchmark"]
    st.caption(f"{stats['inicio']} a {stats['fim']} · custos por lado: {stats['custos']['fee_bps']:.0f} bps de taxas"
               f" + {stats['custos']['slippage_bps']:.0f} bps de slippage · parâmetros: {stats['parametros']}"
               if "custos" in stats else f"{stats['inicio']} a {stats['fim']}")
    if stats["escopo"] == "holdout":
        st.warning("Período reservado: cada consulta reduz o valor dele como teste independente.")

    k = st.columns(5)
    k[0].metric("Retorno anual", pct(s["cagr"]), f"{(s['cagr'] - b['cagr']) * 100:+.1f} p.p. vs BOVA11")
    k[1].metric("Sharpe (excesso ao CDI)", num(s["sharpe"]), f"{s['sharpe'] - b['sharpe']:+.2f} vs BOVA11")
    k[2].metric("Drawdown máximo", pct(s["max_drawdown"]), f"BOVA11 {pct(b['max_drawdown'])}", delta_color="off")
    if ops.get("operacoes"):
        lo, hi = ops["expectativa_ic95"]
        k[3].metric("Expectativa por operação", pct(ops["expectativa"], 2), f"IC 95%: {pct(lo, 2)} a {pct(hi, 2)}",
                    delta_color="off")
        k[4].metric("Operações", ops["operacoes"], f"acerto {ops['taxa_acerto']:.0%} · payoff {ops['payoff']:.2f}",
                    delta_color="off")

    base = curves[list(SERIES)] / curves[list(SERIES)].iloc[0] * 100
    st.plotly_chart(line_chart(base, "Patrimônio (base 100)", ".1f"), width="stretch")
    dd = curves[list(SERIES)] / curves[list(SERIES)].cummax() - 1
    fig = line_chart(dd, "Drawdown", ".1%", cols=("estrategia", "benchmark"))
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader("Desempenho")
        st.dataframe(perf_table(perf), width="stretch")
    with right:
        if ops.get("operacoes"):
            st.subheader("Expectativa matemática")
            st.markdown(
                f"**E = Pg × G − Pp × P** (custos já descontados de cada operação)\n\n"
                f"E = {ops['taxa_acerto']:.1%} × {ops['ganho_medio']:.2%} − {1 - ops['taxa_acerto']:.1%} × "
                f"{ops['perda_media']:.2%} = **{ops['expectativa']:+.2%}** por operação "
                f"({ops['expectativa_R']:+.2f} R, t = {ops['t_stat']:.2f})\n\n"
                f"Fator de lucro {ops['fator_lucro']:.2f} · duração média {ops['duracao_media']:.0f} pregões · "
                f"lucro antes do IR R$ {ops['lucro_liquido']:,.0f} · IR pago R$ {stats.get('imposto_pago', 0):,.0f}")

    trades_path = folder / "trades.csv"
    if trades_path.exists() and ops.get("operacoes"):
        trades = pd.read_csv(trades_path)
        r = trades["r_multiple"].clip(-4, 10)
        fig = go.Figure()
        for name, mask, color in (("Perdedoras", r <= 0, BAD), ("Vencedoras", r > 0, GOOD)):
            fig.add_trace(go.Histogram(x=r[mask], name=name, marker=dict(color=color, line=dict(width=0)),
                                       xbins=dict(start=-4, end=10, size=0.5),
                                       hovertemplate="%{x} R: %{y} operações"))
        layout(fig, "Distribuição do resultado por operação, em múltiplos do risco planejado (R)", 320,
               barmode="overlay", bargap=0.08)
        fig.update_layout(hovermode="closest")
        fig.update_xaxes(ticksuffix=" R")
        st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    for col, name, title in ((c1, "anual", "Retorno por ano"), (c2, "regimes", "Retorno anualizado por regime do BOVA11")):
        p = folder / f"{name}.csv"
        if p.exists():
            df = pd.read_csv(p, index_col=0)
            num_cols = [c for c in df.columns if c != "pregoes"]
            col.subheader(title)
            col.dataframe(df.style.format({c: "{:+.1%}" for c in num_cols}), width="stretch")
    if trades_path.exists():
        with st.expander("Todas as operações"):
            st.dataframe(pd.read_csv(trades_path), width="stretch", hide_index=True)


def page_walkforward(folder: Path) -> None:
    stats = json.loads((folder / "stats.json").read_text(encoding="utf-8"))
    curves = pd.read_parquet(folder / "curves.parquet")
    st.caption(f"Fora da amostra, {stats['inicio']} a {stats['fim']} · {stats['combinacoes_testadas']} combinações de"
               " parâmetros testadas: quanto mais combinações, maior a chance de um bom resultado ser acaso.")
    base = curves[list(SERIES)] / curves[list(SERIES)].iloc[0] * 100
    st.plotly_chart(line_chart(base, "Patrimônio fora da amostra (base 100)", ".1f"), width="stretch")
    st.dataframe(perf_table(stats["desempenho"]), width="stretch")
    st.subheader("Janelas: parâmetros escolhidos no treino e resultado no teste")
    st.dataframe(pd.read_csv(folder / "janelas.csv", index_col=0).style.format(
        {"sharpe_treino": "{:+.2f}", "sharpe_teste": "{:+.2f}", "retorno_teste": "{:+.1%}"}), width="stretch")
    st.subheader("Sharpe de cada combinação no período inteiro")
    st.dataframe(pd.read_csv(folder / "combinacoes.csv", index_col=0).style.format("{:+.2f}"), width="stretch")


def page_sensitivity(folder: Path) -> None:
    tab = pd.read_csv(folder / "tabela.csv")
    base = tab.iloc[0]
    st.caption("A mesma estratégia sob condições perturbadas, no período de desenvolvimento. Uma vantagem real "
               "sobrevive a custos maiores, outro início, outro universo e um dia de atraso.")
    tab["cenario"] = tab["grupo"] + " · " + tab["cenario"]
    fig = go.Figure(go.Bar(
        x=tab["sharpe"], y=tab["cenario"], orientation="h",
        marker=dict(color=[SERIES["estrategia"][1] if i else INK for i in range(len(tab))], line=dict(width=0)),
        hovertemplate="%{y}<br>Sharpe %{x:.2f}<extra></extra>"))
    layout(fig, "Sharpe (excesso ao CDI) por cenário · a primeira barra é a configuração atual", 30 * len(tab) + 80,
           showlegend=False, bargap=0.35)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=AXIS)
    st.plotly_chart(fig, width="stretch")
    st.dataframe(tab.drop(columns="grupo").style.format(
        {"cagr": "{:+.1%}", "sharpe": "{:+.2f}", "max_drawdown": "{:+.1%}", "expectativa": "{:+.2%}"}),
        width="stretch", hide_index=True)
    worst = tab.loc[tab["sharpe"].idxmin()]
    st.markdown(f"Base: Sharpe **{base['sharpe']:+.2f}**. Pior cenário: {worst['cenario']}, "
                f"Sharpe **{worst['sharpe']:+.2f}**.")


def page_hypotheses() -> None:
    from quantlab import registry

    tab = registry.table()
    if tab.empty:
        st.info("Nenhuma hipótese registrada. Rode: python -m quantlab backtest")
        return
    k = st.columns(3)
    k[0].metric("Configurações testadas", tab.attrs["n"])
    k[1].metric("Maior Sharpe esperado por acaso", f"{tab.attrs['sharpe_acaso']:.2f}")
    k[2].metric("Melhor Sharpe obtido", f"{tab['sharpe'].max():+.2f}")
    st.caption("Toda configuração testada no período de desenvolvimento fica registrada. PSR: probabilidade de o "
               "Sharpe verdadeiro ser maior que zero. DSR (Deflated Sharpe): probabilidade de ele superar o que "
               "se esperaria por pura sorte com este número de tentativas. Abaixo de ~95% não há evidência de vantagem.")
    st.dataframe(tab.style.format({"sharpe": "{:+.2f}", "psr": "{:.0%}", "dsr": "{:.0%}"}),
                 width="stretch", hide_index=True)


def page_paper() -> None:
    if not (PAPER / "status.json").exists():
        st.info("Ainda não há paper trading. Rode: python -m quantlab paper")
        return
    s = json.loads((PAPER / "status.json").read_text(encoding="utf-8"))
    st.caption(f"Estratégia {s['estrategia']} · último pregão processado {s['ultimo_pregao']} · "
               f"executado em {s['executado_em']} · nenhuma ordem real é enviada")
    if s["novas_entradas_bloqueadas"]:
        st.error("⛔ Kill switch: novas entradas bloqueadas")
    else:
        st.success("✓ Operação normal: nenhuma trava de risco ativa")
    for a in s["alertas"]:
        st.warning(a)
    for e in s.get("eventos", []):
        st.info(e)
    k = st.columns(5)
    k[0].metric("Patrimônio simulado", f"R$ {s['patrimonio']:,.2f}")
    k[1].metric("Caixa", f"R$ {s['caixa']:,.2f}")
    k[2].metric("Posições", len(s["posicoes"]))
    k[3].metric("Proventos recebidos", f"R$ {s.get('proventos_recebidos', 0):,.2f}")
    k[4].metric("IR pago", f"R$ {s.get('imposto_pago', 0):,.2f}")
    eq = PAPER / "equity.csv"
    if eq.exists():
        e = pd.read_csv(eq, parse_dates=["date"]).set_index("date")
        if len(e) > 1:
            fig = go.Figure(go.Scatter(x=e.index, y=e["equity"], mode="lines", name="Patrimônio",
                                       line=dict(color=SERIES["estrategia"][1], width=2),
                                       hovertemplate="R$ %{y:,.2f}"))
            st.plotly_chart(layout(fig, "Patrimônio simulado (R$)", 300, showlegend=False), width="stretch")
    o = s["ordens_proximo_pregao"]
    c1, c2 = st.columns(2)
    c1.subheader("Compras simuladas na próxima abertura")
    c1.dataframe(pd.DataFrame(o["compras"]), width="stretch", hide_index=True) if o["compras"] else c1.write("Nenhuma.")
    c2.subheader("Vendas simuladas na próxima abertura")
    c2.dataframe(pd.DataFrame(o["vendas"]), width="stretch", hide_index=True) if o["vendas"] else c2.write("Nenhuma.")
    st.subheader("Posições")
    st.dataframe(pd.DataFrame(s["posicoes"]), width="stretch", hide_index=True) if s["posicoes"] else st.write("Nenhuma.")
    if (PAPER / "trades.csv").exists():
        st.subheader("Operações encerradas")
        st.dataframe(pd.read_csv(PAPER / "trades.csv"), width="stretch", hide_index=True)


def page_data() -> None:
    p = DATA / "validation_report.csv"
    if not p.exists():
        st.info("Sem dados. Rode: python -m quantlab data")
        return
    rep = pd.read_csv(p)
    st.caption("Preços oficiais da B3 (COTAHIST), incluindo papéis deslistados. Fonte 'cotahist+yahoo': com "
               "dividendos e desdobramentos; 'cotahist': sem dividendos e com desdobramentos inferidos. Saltos "
               "acima de 40% em um dia são apenas sinalizados: confira se foram eventos reais.")
    st.dataframe(rep, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------- menu

st.title("Quant Lab — swing trade B3 (simulação)")
runs = sorted(p.name for p in RESULTS.glob("*") if (p / "stats.json").exists()) if RESULTS.exists() else []
LABEL = {"dev": "desenvolvimento", "holdout": "reservado", "walkforward": "walk-forward",
         "sensitivity": "sensibilidade"}
with st.sidebar:
    page = st.radio("Seção", ["Pesquisa", "Hipóteses", "Paper trading", "Dados"])
    run = None
    if page == "Pesquisa" and runs:
        names = {r: f"{r.rsplit('_', 1)[0]} · {LABEL.get(r.rsplit('_', 1)[1], r)}" for r in runs}
        run = st.selectbox("Resultado", runs, format_func=lambda r: names.get(r, r))

if page == "Pesquisa":
    if not run:
        st.info("Sem resultados. Rode: python -m quantlab backtest")
    elif run.endswith("walkforward"):
        page_walkforward(RESULTS / run)
    elif run.endswith("sensitivity"):
        page_sensitivity(RESULTS / run)
    else:
        page_backtest(RESULTS / run)
elif page == "Hipóteses":
    page_hypotheses()
elif page == "Paper trading":
    page_paper()
else:
    page_data()

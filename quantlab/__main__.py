"""CLI do laboratório.

  python -m quantlab data                      baixa e valida os dados
  python -m quantlab backtest [-s NOME]        backtest no período de desenvolvimento
  python -m quantlab backtest --holdout        avaliação no período reservado
  python -m quantlab walkforward [-s NOME]     validação walk-forward
  python -m quantlab sensitivity [-s NOME]     teste de sensibilidade
  python -m quantlab hypotheses                registro de hipóteses com Deflated Sharpe
  python -m quantlab paper [--no-update]       avança o paper trading
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from . import pairs, registry, sensitivity
from .backtest import run_backtest
from .config import DATA_DIR, RESULTS_DIR, load_config
from .data import build_dataset, download_cdi, load_panel, universe_mask, validation_report
from .metrics import perf_stats, regime_table, trade_stats, yearly_returns
from .strategies import make_signals
from .validation import walk_forward

RATIOS = ("sharpe", "sortino", "calmar")


def _save(folder, curves: pd.DataFrame | None, stats: dict, **tables: pd.DataFrame) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if curves is not None:
        curves.to_parquet(folder / "curves.parquet")
    (folder / "stats.json").write_text(json.dumps(stats, indent=2, default=str, ensure_ascii=False))
    for k, df in tables.items():
        df.to_csv(folder / f"{k}.csv")


def _curves(equity: pd.Series, panel, capital: float) -> pd.DataFrame:
    b = panel.benchmark.reindex(equity.index).ffill()
    cdi = (1 + panel.cdi.reindex(equity.index).fillna(0)).cumprod()
    return pd.DataFrame({"estrategia": equity, "benchmark": b / b.iloc[0] * capital,
                         "cdi": cdi / cdi.iloc[0] * capital})


def _perf(curves: pd.DataFrame, panel, cfg, exposure=None) -> dict:
    """A curva da estratégia já é líquida de IR; benchmark e CDI pagam no resgate."""
    rate = cfg["tax"]["rate"] if cfg.get("tax", {}).get("enabled") else 0.0
    return {k: perf_stats(curves[k], panel.cdi, exposure if k == "estrategia" else None,
                          final_tax=0.0 if k == "estrategia" else rate) for k in curves}


def _print_perf(title: str, perf: dict[str, dict]) -> None:
    print(f"\n{title}")
    df = pd.DataFrame(perf)
    fmt = lambda k, v: f"{v:.2f}" if k in RATIOS else f"{v:+.1%}"
    print(pd.DataFrame({c: {k: fmt(k, v) if pd.notna(v) else "-" for k, v in df[c].items()}
                        for c in df}).to_string())


def _names(cfg, args) -> list[str]:
    return [args.strategy] if args.strategy != "all" else list(cfg["strategy"])


def cmd_data(cfg, args):
    DATA_DIR.mkdir(exist_ok=True)
    print("Montando a base (COTAHIST + Yahoo)...")
    meta = build_dataset(cfg)
    print("Baixando CDI (Banco Central)...")
    try:
        download_cdi(cfg)
    except Exception as e:
        print(f"AVISO: CDI não baixado ({e})")
    rep = validation_report()
    full = meta.fonte == "cotahist+yahoo"
    print(f"\n{len(meta)} ativos na base, todos com preços oficiais da B3: {full.sum()} com dividendos e "
          f"desdobramentos do Yahoo, {(~full).sum()} sem dividendos (deslistados ou sem cobertura).")
    print(f"{(meta.historico_de.fillna('') != '').sum()} papéis renomeados tiveram o histórico do código antigo emendado.")
    print("Relatório: data/validation_report.csv")
    flagged = rep[(rep.saltos_suspeitos > 0) | (rep.preco_invalido > 0)]
    if len(flagged):
        print(f"\n{len(flagged)} ativos com saltos de preço acima de 40% em um dia (ver relatório).")


def cmd_backtest(cfg, args):
    panel = load_panel(cfg)
    universe = universe_mask(panel, cfg)
    per = cfg["periods"]
    scope = "holdout" if args.holdout else "dev"
    start, end = (per["holdout_start"], None) if args.holdout else (per["dev_start"], per["dev_end"])
    if args.holdout:
        print("ATENÇÃO: período reservado. Cada olhada reduz o valor dele como teste independente.")
    capital = cfg["risk"]["initial_capital"]
    for name in _names(cfg, args):
        params = cfg["strategy"][name]
        if params.get("engine") == "pairs":
            res = pairs.run(panel, universe, cfg, params, start, end)
        else:
            res = run_backtest(panel, make_signals(name, panel, universe, params), cfg, start, end)
        registry.log_trial(name, params, scope, "backtest", res.equity.pct_change().fillna(0.0), panel.cdi)
        curves = _curves(res.equity, panel, capital)
        perf = _perf(curves, panel, cfg, res.exposure)
        ts = trade_stats(res.trades)
        _save(RESULTS_DIR / f"{name}_{scope}", curves.assign(exposicao=res.exposure),
              {"estrategia": name, "escopo": scope, "inicio": str(res.equity.index[0].date()),
               "fim": str(res.equity.index[-1].date()), "parametros": params, "custos": cfg["costs"],
               "desempenho": perf, "operacoes": ts, "posicoes_abertas": res.open_positions,
               "imposto_pago": res.taxes},
              trades=res.trades.set_index("exit_date"),
              anual=yearly_returns({k: curves[k] for k in curves}),
              regimes=regime_table(curves["estrategia"], panel.benchmark))
        _print_perf(f"=== {name} | {scope} | {res.equity.index[0].date()} a {res.equity.index[-1].date()} ===", perf)
        if ts["operacoes"]:
            lo, hi = ts["expectativa_ic95"]
            print(f"\nOperações: {ts['operacoes']} | acerto {ts['taxa_acerto']:.1%} | ganho médio {ts['ganho_medio']:+.2%}"
                  f" | perda média -{ts['perda_media']:.2%} | payoff {ts['payoff']:.2f}")
            print(f"Expectativa por operação (após custos): {ts['expectativa']:+.2%}  IC95% [{lo:+.2%}, {hi:+.2%}]"
                  f"  t={ts['t_stat']:.2f}  |  {ts['expectativa_R']:+.2f} R  |  fator de lucro {ts['fator_lucro']:.2f}")
            print(f"Lucro antes do IR R$ {ts['lucro_liquido']:,.0f} | IR pago R$ {res.taxes:,.0f}")


def cmd_walkforward(cfg, args):
    panel = load_panel(cfg)
    universe = universe_mask(panel, cfg)
    for name in _names(cfg, args):
        if name not in cfg["walkforward"]["grid"]:
            continue
        print(f"\n=== walk-forward: {name} ===")
        wf = walk_forward(name, panel, universe, cfg)
        curves = _curves(wf["equity"], panel, wf["equity"].iloc[0])
        perf = _perf(curves, panel, cfg)
        _save(RESULTS_DIR / f"{name}_walkforward", curves,
              {"estrategia": name, "escopo": "walkforward", "combinacoes_testadas": wf["n_combos"],
               "inicio": str(curves.index[0].date()), "fim": str(curves.index[-1].date()), "desempenho": perf},
              janelas=wf["windows"], combinacoes=wf["combos"])
        print(wf["windows"].to_string(float_format=lambda v: f"{v:+.2f}"))
        _print_perf(f"Fora da amostra ({wf['n_combos']} combinações testadas)", perf)


def cmd_sensitivity(cfg, args):
    panel = load_panel(cfg)
    for name in _names(cfg, args):
        if cfg["strategy"][name].get("engine"):
            continue
        print(f"\n=== sensibilidade: {name} (desenvolvimento) ===")
        tab = sensitivity.run(name, panel, cfg)
        _save(RESULTS_DIR / f"{name}_sensitivity", None, {"estrategia": name, "escopo": "sensitivity"}, tabela=tab)
        print(tab.to_string(formatters={"cagr": "{:+.1%}".format, "sharpe": "{:+.2f}".format,
                                        "max_drawdown": "{:+.1%}".format, "expectativa": "{:+.2%}".format}))


def cmd_hypotheses(cfg, args):
    tab = registry.table()
    if tab.empty:
        print("Nenhuma hipótese registrada. Rode backtest ou walkforward.")
        return
    print(f"{tab.attrs['n']} configurações testadas em desenvolvimento. "
          f"Maior Sharpe esperado por puro acaso: {tab.attrs['sharpe_acaso']:.2f}")
    print("PSR = prob. de o Sharpe verdadeiro ser > 0; DSR = prob. de superar o esperado por acaso.\n")
    show = tab.drop(columns=["quando"]).head(args.top)
    show["parametros"] = show["parametros"].str.slice(0, 70)
    print(show.to_string(index=False, formatters={"sharpe": "{:+.2f}".format, "psr": "{:.0%}".format,
                                                  "dsr": "{:.0%}".format}))


def cmd_paper(cfg, args):
    from .paper import run_paper

    st = run_paper(cfg, update=not args.no_update)
    print(f"Paper [{st['estrategia']}] até {st['ultimo_pregao']} ({st['pregoes_processados']} pregões novos)")
    print(f"Patrimônio R$ {st['patrimonio']:,.2f} | caixa R$ {st['caixa']:,.2f} | {len(st['posicoes'])} posições")
    for a in st["alertas"]:
        print(f"  ALERTA: {a}")
    for e in st["eventos"]:
        print(f"  {e}")
    o = st["ordens_proximo_pregao"]
    print("Ordens simuladas para a próxima abertura:")
    for v in o["vendas"]:
        print(f"  VENDER  {v['ticker']} ({v['motivo']})")
    for c in o["compras"]:
        print(f"  COMPRAR {c['ticker']}  ref {c['ref_fechamento']:.2f}  stop ~{c['stop_estimado']:.2f}")
    if not o["vendas"] and not o["compras"]:
        print("  (nenhuma)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="quantlab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data")
    for n in ("backtest", "walkforward", "sensitivity"):
        p = sub.add_parser(n)
        p.add_argument("-s", "--strategy", default="all" if n != "sensitivity" else cfg["paper"]["strategy"],
                       choices=[*cfg["strategy"], "all"])
        if n == "backtest":
            p.add_argument("--holdout", action="store_true")
    sub.add_parser("hypotheses").add_argument("--top", type=int, default=15)
    sub.add_parser("paper").add_argument("--no-update", action="store_true")
    args = ap.parse_args()
    {"data": cmd_data, "backtest": cmd_backtest, "walkforward": cmd_walkforward,
     "sensitivity": cmd_sensitivity, "hypotheses": cmd_hypotheses, "paper": cmd_paper}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()

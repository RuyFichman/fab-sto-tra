# AGENTS.md

Instruções para agentes de IA que trabalham neste repositório.

## O que é

Laboratório quantitativo pessoal de swing trade na B3. Roda localmente, é de uso
não comercial e **só simula**: não existe, e não deve ser criado sem pedido
explícito do usuário, nenhum código que envie ordens reais a corretora.

O objetivo não é gerar sinais de compra. É responder se uma regra tem
expectativa positiva depois de custos e imposto, fora dos dados em que foi
desenvolvida. Um resultado negativo honesto é uma entrega válida.

Idioma do projeto: português (código comentado, saídas da CLI, documentação e
nomes de colunas dos resultados). Identificadores de código em inglês.

## Ambiente

- Windows 10, PowerShell. Python 3.13 em `.venv`.
- Use sempre o Python do venv: `.\.venv\Scripts\python.exe`.
- Repositório remoto: https://github.com/RuyFichman/fab-sto-tra. Não faça
  commit nem push sem pedido. `data/`, `paper/` e `results/` (exceto
  `hypotheses.csv`) ficam fora do versionamento; ver `.gitignore`.
- Dependências em `requirements.txt`.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests          # testes (rápidos, ~2 s, sem rede)
.\.venv\Scripts\python.exe -m quantlab data            # rebaixa/remonta a base (rede, minutos)
.\.venv\Scripts\python.exe -m quantlab backtest [-s NOME]
.\.venv\Scripts\python.exe -m quantlab walkforward [-s NOME]
.\.venv\Scripts\python.exe -m quantlab sensitivity [-s NOME]
.\.venv\Scripts\python.exe -m quantlab hypotheses
.\.venv\Scripts\python.exe -m quantlab paper --no-update   # sem rede
.\.venv\Scripts\streamlit.exe run dashboard/app.py
```

Para verificar o dashboard sem navegador, use `streamlit.testing.v1.AppTest`
em `dashboard/app.py` e percorra as opções da barra lateral conferindo
`at.exception`.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `config.toml` | Toda a configuração: períodos, custos, IR, risco, estratégias, grades do walk-forward |
| `quantlab/data.py` | COTAHIST, fatores de ajuste, painel de preços, universo por liquidez |
| `quantlab/strategies.py` | Indicadores e sinais (`STRATEGIES` por papel, `CROSS_SECTIONAL` por ranking) |
| `quantlab/engine.py` | Motor único de risco e execução, passo a passo, com estado serializável |
| `quantlab/backtest.py` | Laço do backtest sobre o motor |
| `quantlab/pairs.py` | Arbitragem entre pares: simulação separada, comprada e vendida |
| `quantlab/validation.py` | Walk-forward |
| `quantlab/sensitivity.py` | Perturbações de custos, início, universo, atraso |
| `quantlab/registry.py` | Registro de hipóteses e Deflated Sharpe |
| `quantlab/metrics.py` | Desempenho, expectativa, PSR/DSR, regimes |
| `quantlab/paper.py`, `alerts.py` | Paper trading e notificações |
| `quantlab/__main__.py` | CLI |
| `dashboard/app.py` | Dashboard Streamlit (lê `results/`, `paper/`, `data/`) |
| `tests/test_engine.py` | Testes do motor, dos sinais e das métricas |
| `docs/` | Documentação de apoio (ver abaixo) |

Gerados, não editar à mão: `data/` (cache de dados), `results/` (saídas e
`hypotheses.csv`), `paper/` (estado da conta simulada).

Documentos de apoio:

- `README.md`: visão do usuário, regras de simulação, limitações.
- `docs/dados.md`: como a base é montada e as armadilhas já encontradas. Leia antes de tocar em `data.py`.
- `docs/pesquisa.md`: hipóteses já testadas e seus resultados. Leia antes de propor ou testar uma estratégia.
- `CONTRIBUTING.md`: fluxo de trabalho e padrão de commits. `CHANGELOG.md`: atualize a cada mudança visível.
- `SECURITY.md`: o que nunca pode ir para o repositório.

## Invariantes que não podem ser quebrados

1. **Sem olhar o futuro.** O sinal da data *t* usa só dados até o fechamento de
   *t* e executa na abertura de *t+1*. Toda estratégia nova entra no teste
   parametrizado `test_signals_have_no_lookahead`.
2. **Um motor só.** Backtest e paper usam `Engine.step`. Não duplique lógica de
   execução em outro lugar.
3. **Preços vêm do COTAHIST.** O Yahoo fornece apenas fatores de ajuste e os
   pregões recentes; seus preços históricos têm erros (ver `docs/dados.md`).
4. **Universo ponto-no-tempo.** Quem é elegível em cada data depende só da
   liquidez conhecida até aquela data, incluindo papéis hoje deslistados.
5. **Só comprado, sem alavancagem**, com custos e IR sempre ligados nos
   resultados reportados. Única exceção: `pairs.py`, pesquisa isolada que
   nunca alimenta o paper.
6. **Estado do paper é compatível para trás.** Campos novos em `State` e
   `Position` precisam de valor padrão; `paper/state.json` existente deve
   continuar carregando.

## Disciplina de pesquisa

- Período de desenvolvimento: 2015–2022. **Período reservado: 2023 em diante.**
  Nunca rode `backtest --holdout` nem inspecione resultados desse período sem
  pedido explícito do usuário. Ele só deve ser aberto uma vez, com a estratégia
  congelada.
- Não ajuste parâmetros para melhorar um resultado e reportar só o melhor. Cada
  configuração testada é registrada automaticamente em `results/hypotheses.csv`
  e conta contra o Deflated Sharpe. Não apague nem edite esse arquivo.
- Fixe os parâmetros de uma hipótese nova **antes** de rodar, com justificativa
  econômica, em um comentário no `config.toml`. Depois de rodar, anote o
  resultado no mesmo comentário e em `docs/pesquisa.md`, inclusive quando for
  negativo.
- Reporte resultados como saem: após custos e IR, comparados com BOVA11 e CDI,
  com o walk-forward. Não arredonde a favor nem omita o que piorou.
- Teste de sensibilidade não é hipótese nova e não entra no registro.

## Convenções de código

- Uma estratégia por papel é uma função `(df, params) -> DataFrame` com colunas
  `entry`, `exit`, `atr`, `rank`, registrada em `STRATEGIES`. Uma estratégia de
  ranking entre papéis é `(panel, universe, params) -> dict` em
  `CROSS_SECTIONAL`. Variante de parâmetros: seção `[strategy.nome]` com
  `base = "outra"`. Limites de risco próprios: `risk = { ... }` na seção.
- Indicadores por papel são calculados só sobre os pregões em que o papel
  negociou (`dropna` antes, `reindex` depois).
- Mudou o comportamento do motor: escreva o teste junto, com números que dê
  para conferir de cabeça (ver os testes existentes).
- Comentários explicam o porquê; mensagens ao usuário em português.
- Gráficos do dashboard: cores fixas por série definidas em `SERIES`, um eixo
  por gráfico, texto em cor neutra.

## Cuidados operacionais

- Existe uma tarefa agendada do Windows, "QuantLab Paper Trading" (dias úteis às
  19:00), que roda `run_paper.bat`. Não a remova nem altere sem pedido.
- `paper/` é o histórico da conta simulada. Não apague nem reinicie sem pedido;
  se uma mudança exigir reinício, faça backup em uma subpasta e avise.
- `python -m quantlab data` apaga e remonta `data/raw/`. Os arquivos em
  `data/cotahist/` são cache de downloads grandes (~600 MB): não apague.
- Baixar dados é permitido (B3, Yahoo, Banco Central). Não envie dados do
  usuário a serviços externos. O Telegram só é usado se o usuário preencher o
  token em `[alerts]`.
- A barra do dia só é confiável após as 18:30 de Brasília; o paper já ignora a
  barra parcial antes disso.

## Antes de dizer que terminou

1. `pytest -q tests` passa.
2. O comando afetado foi executado de verdade e a saída conferida.
3. Se mexeu no dashboard, todas as páginas carregam sem exceção.
4. `README.md`, `CHANGELOG.md` e os arquivos em `docs/` refletem a mudança.

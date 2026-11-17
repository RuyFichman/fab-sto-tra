# Quant Lab — swing trade quantitativo na B3 (simulação)

Laboratório pessoal para criar, testar e acompanhar estratégias de swing trade.
Roda localmente e **não envia ordens reais**: a execução é sempre simulada.

A pergunta que ele responde não é "o que comprar", e sim: *esta regra tem
expectativa positiva depois de custos, fora dos dados em que foi desenvolvida?*

## Uso

```powershell
python -m venv .venv                                   # só na primeira vez
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1
python -m quantlab data            # baixa COTAHIST (B3), fatores de ajuste (Yahoo) e CDI (Banco Central)
python -m quantlab backtest        # backtest no período de desenvolvimento
python -m quantlab walkforward     # validação walk-forward
python -m quantlab sensitivity     # teste de sensibilidade (padrão: estratégia do paper)
python -m quantlab hypotheses      # registro de hipóteses com Deflated Sharpe
python -m quantlab paper           # avança o paper trading (agendado: dias úteis às 19h)
streamlit run dashboard/app.py     # dashboard
pytest tests                       # testes do motor
```

Tudo é configurado em `config.toml`. Rode `data` de tempos em tempos: é ele que
atualiza a lista de papéis do universo.

Mais documentação: `docs/dados.md` (como a base é montada e suas armadilhas),
`docs/pesquisa.md` (hipóteses testadas e resultados), `CONTRIBUTING.md`,
`CHANGELOG.md`, `SECURITY.md` e `AGENTS.md` (regras para agentes de IA).

## Componentes

| Parte | Arquivo | O que faz |
|---|---|---|
| Market Data | `quantlab/data.py` | Preços oficiais, ajustes, relatório de qualidade, universo por liquidez em cada data |
| Quant Lab | `quantlab/strategies.py`, `validation.py`, `sensitivity.py`, `metrics.py` | Sinais, walk-forward, sensibilidade, expectativa, regimes |
| Registro de hipóteses | `quantlab/registry.py` | Anota toda configuração testada e calcula o Deflated Sharpe |
| Risk + Execution Engine | `quantlab/engine.py` | Dimensionamento por risco, limites, stops, custos, IR, kill switch |
| Paper trading | `quantlab/paper.py`, `alerts.py` | Conta simulada com estado em `paper/`, proventos e alertas |
| Dashboard | `dashboard/app.py` | Resultados, hipóteses, sensibilidade, paper e qualidade dos dados |

O mesmo motor roda o backtest e o paper trading, então o que foi testado é o que é simulado no dia a dia.

## Dados

- **Preços e volumes**: arquivos anuais COTAHIST da B3, guardados em `data/cotahist/`. Trazem todos os papéis que já negociaram, inclusive os deslistados, o que remove o viés de sobrevivência. Entra na base todo papel que já esteve entre os `candidate_top_n` mais líquidos.
- **Dividendos e desdobramentos**: Yahoo Finance, só como fator de ajuste. Os preços históricos do Yahoo não são usados: têm barras erradas em cerca de 2% dos dias.
- **Papéis renomeados** (ex.: ELET3 → AXIA3): o histórico do código antigo é emendado ao novo.
- **Papéis deslistados**: sem dividendos (retorno subestimado) e com desdobramentos inferidos do preço. Uma posição em papel que para de negociar é liquidada no último preço após 10 pregões.
- **Pregões mais recentes** que o COTAHIST local ainda não tem vêm do Yahoo; o paper rebaixa o COTAHIST do ano uma vez por semana.

## Regras de simulação

- Sinal calculado no fechamento de *t*, executado na abertura de *t+1*.
- Custo por lado: taxas (`fee_bps`) + meio spread (`slippage_bps`) + impacto de mercado, que cresce com a raiz do tamanho da ordem em relação ao volume do papel (`impact_y`). A ordem é limitada a `max_participation` do volume.
- IR de 15% sobre o ganho líquido do mês, descontado do caixa no mês seguinte, com compensação de prejuízos e isenção quando as vendas do mês ficam abaixo de R$ 20 mil. Benchmark e CDI são comparados com IR no resgate ("após IR").
- Stop intradiário executa no preço do stop; se a abertura já vem abaixo dele, executa na abertura — a perda pode superar o risco planejado.
- Só comprado, sem alavancagem. Caixa parado não rende, a menos que a estratégia defina `cash_cdi`.
- Quantidade = risco por operação ÷ distância do stop, limitada por teto por posição, exposição total e caixa.
- Sharpe é calculado em excesso ao CDI.

## Estratégias (hipóteses, não regras comprovadas)

- **breakout**: fechamento acima da máxima de 20 pregões e acima da média de 200; stop inicial de 2 ATR; saída no fechamento abaixo da mínima de 10 pregões.
- **breakout_regime**: breakout com filtro de mercado (rejeitada; resultado anotado no `config.toml`).
- **momentum**: momentum relativo de 12 meses, rebalanceado no primeiro pregão do mês.
- **momentum_abs**: momentum que também exige retorno acima do CDI.
- **breakout_cdi**, **momentum_abs_cdi**: variantes com o caixa parado rendendo 80% do CDI.
- **pairs**: arbitragem entre pares, comprada e vendida, em simulação separada do motor (`quantlab/pairs.py`).
- **meanrev**: RSI(2) baixo em tendência de alta; saída acima da média curta ou por tempo.

Para adicionar outra, escreva uma função em `strategies.py`, registre em `STRATEGIES` (por papel) ou `CROSS_SECTIONAL` (ranking entre papéis) e crie `[strategy.nome]` no `config.toml`. Uma variante de parâmetros usa `base = "nome"`.

## Disciplina de pesquisa

- `dev` (2015–2022) é livre para pesquisar. O período a partir de 2023 é **reservado**: só roda com `backtest --holdout`. Congele a estratégia antes e olhe uma vez; cada consulta seguida de ajuste transforma o holdout em dados de desenvolvimento.
- Toda configuração testada em `dev` entra em `results/hypotheses.csv`. O **Deflated Sharpe** desconta do resultado a sorte de ter tentado muitas vezes: abaixo de ~95%, não há evidência de vantagem.
- O teste de sensibilidade perturba custos, data de início, universo e atraso de execução. Uma vantagem real sobrevive a isso.

## Limitações conhecidas

- Papéis deslistados entram sem dividendos, e os desdobramentos deles são inferidos por heurística (listados em `data/universe_meta.csv`).
- Quando o Yahoo não republica o histórico de um papel renomeado, o código novo começa do zero e só entra no universo depois de 252 pregões.
- No paper, dividendos e JCP são creditados pelo valor bruto na data ex, e os eventos dependem do cadastro do Yahoo, que omite algumas bonificações.
- O IR do último mês de um backtest não é descontado, e a regra de IR na fonte ("dedo-duro") é ignorada.
- Walk-forward recorta retornos de simulações do período inteiro; posições não são zeradas nas fronteiras das janelas.

## Alertas e kill switch (paper)

O paper avisa por notificação do Windows quando há ordens para o próximo pregão,
operações encerradas, proventos ou travas de risco. Para receber também no
Telegram, preencha `telegram_token` e `telegram_chat_id` em `[alerts]`.

Novas entradas são bloqueadas quando: os dados estão defasados, a atualização falha,
o drawdown passa de `max_drawdown_halt`, ou existe o arquivo `paper/KILL`
(crie-o para travar manualmente; apague para liberar). Saídas e stops continuam funcionando.

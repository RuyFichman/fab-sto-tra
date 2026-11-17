# Changelog

Mudanças visíveis do projeto, da mais recente para a mais antiga. Formato
baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

Mudanças que alteram os números dos backtests estão marcadas com **(muda
resultados)**: comparações com versões anteriores deixam de valer.

## [Não lançado]

## [0.4.0] - 2026-11-16

### Adicionado
- Hipótese `momentum_abs`: momentum relativo que também exige retorno acima do CDI.
- Opção `cash_cdi` por estratégia: caixa parado rende uma fração do CDI.
  Variantes `breakout_cdi` e `momentum_abs_cdi`.
- Hipótese `pairs`: arbitragem estatística entre pares pelo método da distância,
  em simulação separada, comprada e vendida, com aluguel (`quantlab/pairs.py`).
- `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, `requirements.txt`, `.gitignore`.

### Resultados
- Nenhuma das novas hipóteses tem evidência de vantagem. `breakout_cdi` é a
  melhor configuração até aqui (8,9% ao ano, Sharpe 0,09, Deflated Sharpe 1%);
  `pairs` foi rejeitada (−0,5% ao ano). Detalhes em `docs/pesquisa.md`.

## [0.3.0] - 2026-11-16

### Adicionado
- `AGENTS.md`, `CLAUDE.md`, `docs/dados.md` e `docs/pesquisa.md`.

## [0.2.0] - 2026-11-16

### Alterado
- **(muda resultados)** Preços passam a vir dos arquivos oficiais COTAHIST da
  B3, incluindo papéis deslistados; o universo deixa de ser uma lista fixa de
  papéis atuais. O Yahoo fica só com os fatores de dividendos e desdobramentos.
- **(muda resultados)** IR de 15% descontado do caixa mês a mês, com compensação
  de prejuízo e isenção de vendas até R$ 20 mil; benchmark e CDI comparados após IR.
- **(muda resultados)** Custo de execução ganha impacto de mercado proporcional
  à raiz do tamanho da ordem, e a ordem é limitada a 1% do volume do papel.
- Conta do paper reiniciada com os preços oficiais (estado anterior em
  `paper/backup_yahoo/`).

### Adicionado
- Emenda do histórico de papéis renomeados (ex.: ELET3 → AXIA3).
- Liquidação automática de posição em papel que para de negociar.
- Hipótese `momentum` (momentum relativo de 12 meses).
- Registro de hipóteses com Probabilistic e Deflated Sharpe (`hypotheses`).
- Teste de sensibilidade (`sensitivity`).
- Paper: crédito de dividendos, ajuste de desdobramentos, notificação do
  Windows e Telegram opcional.
- Dashboard: páginas de hipóteses e de sensibilidade.

### Corrigido
- Preços do Yahoo com erro em cerca de 2% dos dias geravam rompimentos falsos.
- Leitura do COTAHIST perdia pregões quando o arquivo tinha uma linha de
  tamanho irregular.
- Falha passageira da API do Banco Central bloqueava novas entradas no paper.

## [0.1.0] - 2026-11-16

### Adicionado
- Coleta de dados (Yahoo e CDI do Banco Central) com relatório de qualidade.
- Motor único de risco e execução para backtest e paper trading.
- Hipóteses `breakout`, `meanrev` e `breakout_regime`.
- Validação walk-forward e período reservado (2023 em diante).
- Paper trading com kill switch e tarefa agendada em dias úteis às 19h.
- Dashboard em Streamlit.

# Dados: como a base é montada

Tudo isto está em `quantlab/data.py`. `python -m quantlab data` executa o
processo inteiro e grava um arquivo por papel em `data/raw/`.

## Fontes

| Fonte | Uso | Observações |
|---|---|---|
| COTAHIST (B3) | Preços e volumes de todos os papéis | Arquivos anuais `COTAHIST_A{ano}.ZIP` em `data/cotahist/`; preços como negociados, sem ajuste |
| Yahoo Finance | Fatores de dividendos e desdobramentos; pregões recentes | Preços históricos **não** são usados |
| Banco Central (SGS 12) | CDI diário | API limita a janelas de 10 anos; falha passageira (502) é comum |

## Etapas

1. **Download.** Anos encerrados ficam em cache. O ano corrente é rebaixado pelo
   comando `data` sempre, e pelo paper quando a cópia tem mais de 7 dias.
2. **Leitura.** Layout de largura fixa, registros tipo `01`, mercado à vista
   (`010`), BDI `02` (ações e units em lote padrão) e `14` (ETFs, só para o
   benchmark). Aceita códigos terminados em 3, 4, 5, 6 ou 11. O resultado de
   cada ano fica em cache `.parquet` ao lado do `.ZIP`.
3. **Candidatas.** Todo papel que em alguma data esteve entre os
   `candidate_top_n` mais líquidos (mediana de 60 pregões do volume financeiro).
4. **Ajuste dos papéis ativos.** Preço ajustado = oficial × S × A, onde
   A = `adj_close / close` do Yahoo (dividendos) e S vem de `split_factor`.
5. **Emenda de renomeados.** Quando o Yahoo traz histórico anterior ao primeiro
   pregão do código no COTAHIST, procura-se um código que termina onde o novo
   começa e cujos retornos têm correlação acima de 0,9 com o Yahoo; os preços
   oficiais dele são emendados. Repete-se em cadeia.
6. **Papéis sem Yahoo** (deslistados): `infer_splits` e nenhum dividendo.
7. **Relatórios.** `data/universe_meta.csv` (fonte, emendas, desdobramentos
   inferidos, divergência em relação ao Yahoo) e `data/validation_report.csv`.

Colunas de cada arquivo em `data/raw/`: `open, high, low, close` (como
negociados), `adj_close`, `volume`, `turnover` (R$), `dividend` (R$ por ação na
data ex, na escala da época), `split` (proporção na data do evento).

## Armadilhas já encontradas

- **Preços do Yahoo têm erro em cerca de 2% dos dias**: barras com abertura,
  máxima, mínima e fechamento iguais e fora do preço real, ou fechamento
  diferente do oficial. Em um backtest isso cria rompimentos falsos. Por isso o
  Yahoo só entra como razão `adj_close / close` e como razão de preços filtrada
  por mediana.
- **O cadastro de desdobramentos do Yahoo omite bonificações** (ITSA4, CMIG4,
  BRAP4, SANB11 e outros), embora o preço dele esteja ajustado por elas. Por
  isso S é derivado da razão `close do Yahoo / close oficial`, em degraus, e não
  da coluna `Stock Splits`. Essa coluna só é usada para a cauda recente e para
  os eventos do paper.
- **O COTAHIST não vem ordenado por data.** Ordene antes de qualquer
  `pct_change` ou `rolling`; `load_cotahist` já devolve ordenado por papel e data.
- **Um arquivo anual pode ter uma linha de tamanho irregular** (aconteceu em
  2026). A leitura em bloco desalinha e perde pregões em silêncio; o leitor
  detecta isso e passa a filtrar linha a linha. Se o número de pregões por
  papel parecer baixo, confira esse caminho.
- **Colapso real não é desdobramento.** `infer_splits` só aceita um salto como
  desdobramento se a razão for redonda (até 5%) e o volume financeiro do dia for
  normal; em um colapso o volume explode (ex.: AMER3 em janeiro de 2023).
- **Falhas em lote do Yahoo são passageiras.** `yahoo_with_retry` repete os que
  faltaram. Um papel ativo que continue sem Yahoo cai no caminho heurístico.
- **Em 26/10/2026 houve uma queda real do mercado** (BOVA11 de 201,69 para
  172,42), confirmada nos dados oficiais. Não é erro de dados.

## Como conferir a base depois de mexer

- `divergencia_yahoo` em `universe_meta.csv` deve ficar perto de zero (máximo
  observado: 0,011). Acima de 0,10 o papel cai para o caminho heurístico.
- Nenhum papel ativo deve aparecer com `fonte = cotahist`.
- O número de pregões de um papel antigo e líquido (PETR4) deve bater com o do
  benchmark.

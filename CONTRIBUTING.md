# Como contribuir

Projeto pessoal e de uso não comercial. Este guia vale para quem mexer no
código, humano ou agente de IA (para agentes, ver também `AGENTS.md`).

Repositório: https://github.com/RuyFichman/fab-sto-tra

## Preparar o ambiente

Requer Python 3.13 no Windows (os comandos abaixo são PowerShell).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m quantlab data      # baixa ~600 MB da B3 na primeira vez
.\.venv\Scripts\python.exe -m pytest -q tests
```

`data/`, `paper/` e `results/` são gerados localmente e não são versionados
(exceto `results/hypotheses.csv`, o registro de hipóteses).

## Fluxo de trabalho

1. Crie um branch a partir de `main`: `feat/...`, `fix/...`, `docs/...` ou `pesquisa/...`.
2. Faça a mudança com o teste junto.
3. Rode a verificação abaixo.
4. Atualize `CHANGELOG.md` (seção "Não lançado") e a documentação afetada.
5. Abra um pull request descrevendo o que mudou e, se for pesquisa, o resultado
   obtido, bom ou ruim.

## Verificação antes de enviar

- `pytest -q tests` passa.
- O comando afetado foi executado e a saída conferida.
- Se mexeu no dashboard, todas as páginas abrem sem erro.
- Se mexeu em `quantlab/data.py`, a base foi remontada e conferida conforme
  `docs/dados.md` ("Como conferir a base depois de mexer").

## Regras do motor e dos sinais

- O sinal da data *t* usa só dados até o fechamento de *t* e executa em *t+1*.
  Estratégia nova entra no teste `test_signals_have_no_lookahead`.
- Backtest e paper usam o mesmo `Engine.step`. Não duplique lógica de execução.
- Preços vêm do COTAHIST; o Yahoo só fornece fatores de ajuste.
- Campos novos em `State` e `Position` precisam de valor padrão, para que
  `paper/state.json` antigo continue carregando.
- Testes do motor usam números que dá para conferir de cabeça.

## Regras de pesquisa

Estas valem mais do que qualquer regra de código.

- **Período reservado (2023 em diante) não se abre.** `backtest --holdout` só
  com decisão explícita do dono do projeto, uma vez, com a estratégia congelada.
- **Fixe a hipótese antes de rodar.** Escreva a justificativa econômica e os
  parâmetros em um comentário no `config.toml`. Depois de rodar, anote o
  resultado no mesmo comentário e em `docs/pesquisa.md`.
- **Resultado negativo também é registrado.** Não apague hipóteses que falharam
  nem linhas de `results/hypotheses.csv`: é esse registro que permite descontar
  a sorte de ter tentado muitas vezes.
- **Reporte após custos e IR**, ao lado de BOVA11 e CDI, com o walk-forward e o
  Deflated Sharpe. Não escolha o melhor de vários ajustes para mostrar.

## Mensagens de commit

Em português, no imperativo, com prefixo:

```
feat: adiciona filtro de momentum absoluto
fix: tolera linha irregular no COTAHIST
docs: registra resultado da arbitragem de pares
test: cobre liquidação de papel deslistado
pesquisa: testa pares pelo método da distância
```

## O que não vai para o repositório

Tokens, o conteúdo de `paper/` e os dados baixados. Detalhes em `SECURITY.md`.

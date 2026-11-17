# Segurança

## O que este projeto faz e não faz

- **Não envia ordens.** Não há integração com corretora, e nenhuma credencial
  de corretora deve ser adicionada ao código ou à configuração.
- Acessa a internet apenas para baixar dados públicos: B3 (COTAHIST), Yahoo
  Finance e Banco Central. O Telegram só é chamado se você configurar um token.

## O que nunca vai para o repositório

| Item | Por quê | Como está protegido |
|---|---|---|
| Token e chat do Telegram | Dão acesso ao seu bot | Use as variáveis `QUANTLAB_TELEGRAM_TOKEN` e `QUANTLAB_TELEGRAM_CHAT_ID`; deixe os campos de `[alerts]` vazios no `config.toml` |
| `paper/` | Histórico da sua conta simulada | `.gitignore` |
| `data/` | ~600 MB de dados baixados; redistribuição sujeita aos termos da B3 e do Yahoo | `.gitignore` |
| `.venv/` | Ambiente local | `.gitignore` |

Antes de cada commit, confira com `git status` que nada disso entrou. Se um
token for publicado por engano, revogue-o no BotFather; apagar o commit não basta.

## Dados de terceiros

Os dados da B3 e do Yahoo são para uso pessoal. Não publique os arquivos
baixados nem resultados que permitam reconstruí-los.

## Relatar um problema

Abra uma issue em https://github.com/RuyFichman/fab-sto-tra/issues. Se o
problema envolver um segredo exposto, não cole o segredo na issue.

## Aviso

Software de pesquisa, sem garantia. Os resultados são simulações com limitações
conhecidas (ver `README.md`) e não são recomendação de investimento.

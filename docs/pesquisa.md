# Pesquisa: hipóteses testadas

Registro em prosa do que já foi testado e do que se aprendeu. O registro
numérico completo, com Deflated Sharpe, é `results/hypotheses.csv`
(`python -m quantlab hypotheses`).

Regras: toda hipótese entra aqui, inclusive as que falharam; os números são do
período de desenvolvimento (2015–2022), após custos e IR; o período reservado
(2023 em diante) nunca foi aberto.

## Situação em 16/11/2026

Nenhuma estratégia testada mostra vantagem com evidência estatística. Foram 35
configurações; o melhor Sharpe obtido foi +0,09 (breakout com caixa no CDI), com
Deflated Sharpe de 1%, muito abaixo dos ~95% que indicariam algo além de sorte.
Não há estratégia que justifique abrir o período reservado.

Referências no mesmo período: BOVA11 rende 10,8% ao ano (9,6% após IR, Sharpe
0,21, drawdown de −46,9%); CDI rende 8,6% ao ano (7,6% após IR).

| Hipótese | Retorno anual | Sharpe | Drawdown | Walk-forward (anual) | Veredito |
|---|---|---|---|---|---|
| breakout_cdi | +8,9% | +0,09 | −20,0% | não rodado | Melhor até aqui, sem evidência |
| momentum_abs_cdi | +7,8% | +0,05 | −31,5% | não rodado | Sem evidência |
| momentum_abs | +6,4% | −0,02 | −31,9% | +0,1% | Sem vantagem |
| breakout | +6,3% | −0,07 | −21,9% | +2,9% | Sem vantagem |
| momentum | +6,1% | −0,04 | −30,8% | +3,4% | Sem vantagem |
| breakout_regime | +1,7% | −0,39 | −28,4% | −0,4% | Rejeitada |
| meanrev | +0,1% | −1,29 | −15,2% | −0,8% | Rejeitada |
| pairs | −0,5% | −0,89 | −23,7% | não rodado | Rejeitada |

## Hipóteses

### breakout

Fechamento acima da máxima de 20 pregões, com o preço acima da média de 200;
stop de 2 ATR; saída abaixo da mínima de 10 pregões.

- Tem expectativa positiva por operação (+1,63%, IC 95% de +0,59% a +2,68%, 599
  operações, 37% de acerto, payoff 2,46), mas a exposição média de 61% e os
  custos deixam o retorno abaixo do CDI.
- Walk-forward: ganhou em 2018–2020 e perdeu em 2021 (−17%) e 2022 (−4%).
- Sensibilidade: Sharpe entre −0,27 e +0,09 em todos os cenários. Um pregão de
  atraso leva o retorno a 4,1%; custos dobrados, a 4,8%; sem IR, a 7,5%.
- É a estratégia do paper, mantida para validar a infraestrutura.

### breakout_regime

Breakout que só abre posições com o BOVA11 acima da média de 200 pregões.
Motivada pelas perdas de 2021–2022, portanto otimista por construção, e mesmo
assim piorou. O filtro corta as recuperações após quedas (2016, 2020), que era
onde o breakout mais ganhava. Não testar de novo nessa forma.

### momentum

Momentum relativo de 12 meses excluindo o último, 10 papéis, rebalanceado no
primeiro pregão do mês, stop de 5 ATR. Parâmetros convencionais da literatura,
fixados antes de rodar. Expectativa por operação de +10,3%, mas com intervalo de
confiança que inclui zero (137 operações). Drawdown maior que o do breakout.

### meanrev

RSI(2) abaixo de 10 com o preço acima da média de 200; saída acima da média de
5 pregões ou em 10 pregões. Acerta 63% das vezes com payoff de 0,60:
expectativa indistinguível de zero (+0,02%) antes mesmo de considerar o custo de
oportunidade do caixa. As 8 combinações da grade perdem para o CDI.

### breakout_cdi e momentum_abs_cdi (caixa rendendo 80% do CDI)

Mesmos sinais, mas o caixa parado rende 80% do CDI, aproximando um fundo DI já
líquido de IR. O breakout sobe de 6,3% para 8,9% ao ano: fica acima do CDI após
IR (7,6%) e abaixo do BOVA11 após IR (9,6%), com menos da metade do drawdown
(−20% contra −47%). O ganho vem inteiro do rendimento do caixa; a expectativa por
operação não muda (+1,62%). É uma correção de premissa mais do que uma
estratégia nova: a comparação anterior punia quem ficava em caixa. Ainda assim o
Sharpe é 0,09 e o Deflated Sharpe 1%.

### momentum_abs

Momentum relativo que também exige que o papel tenha rendido mais que o CDI na
janela. Em desenvolvimento quase não muda (6,4% contra 6,1%), porque os 10
primeiros do ranking raramente rendem menos que o CDI; no walk-forward piora
(0,1% ao ano contra 3,4%). Não resolve as perdas de 2021 (−19%).

### pairs

Arbitragem estatística pelo método da distância (Gatev et al.): 20 pares mais
próximos em 252 pregões, operados por 126, entrada a 2 desvios, aluguel de 3% ao
ano. Simulação separada do motor principal, sem IR (`quantlab/pairs.py`).
Perdeu dinheiro: −0,5% ao ano, Sharpe −0,89. As 417 operações acertam 57% das
vezes mas ganham menos do que perdem (payoff 0,75), e a expectativa é zero
(−0,03%) depois dos custos das duas pernas. Perdeu em 2015, 2018, 2019 e 2021.

## Ideias ainda não testadas

Anotadas para referência; cada uma conta como nova tentativa quando for rodada.

- Walk-forward das variantes com caixa no CDI (ainda não têm grade).
- Carteira que combina breakout e momentum (falta medir a correlação entre as duas curvas).
- Pares por cointegração dentro do mesmo setor, em vez de distância no universo
  inteiro. Só vale se houver motivo para esperar custo menor que o do método atual.

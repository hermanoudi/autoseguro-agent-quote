## ADDED Requirements

### Requirement: Qualificação de dados do lead
O sistema SHALL conduzir uma conversa em linguagem natural para coletar os dados
necessários para cotar um plano de seguro de veículo: idade do lead, ano do veículo,
CEP, plano desejado e, opcionalmente, data de início de vigência. O sistema SHALL
perguntar apenas pelos dados ainda não informados e SHALL confirmar os dados coletados
antes de acionar a cotação.

#### Scenario: Lead fornece todos os dados de uma vez
- **WHEN** o lead informa idade, veículo com ano, CEP e plano desejado em uma única
  mensagem
- **THEN** o sistema extrai todos os campos, confirma os dados coletados com o lead e
  segue para a cotação sem perguntar novamente pelo que já foi informado

#### Scenario: Lead fornece dados aos poucos
- **WHEN** o lead informa apenas parte dos dados necessários
- **THEN** o sistema pergunta especificamente pelos campos que faltam, um de cada vez ou
  agrupados, sem repetir perguntas sobre dados já confirmados

#### Scenario: Lead corrige um dado já informado
- **WHEN** o lead envia uma mensagem alterando um valor anteriormente informado (por
  exemplo, corrigindo o ano do veículo)
- **THEN** o sistema atualiza o dado e confirma a correção antes de prosseguir

### Requirement: O LLM nunca calcula nem estima preço
O sistema SHALL apresentar ao lead somente valores de prêmio que tenham vindo de uma
resposta HTTP 200 real da `/quote`. O componente de linguagem natural SHALL apenas
extrair parâmetros e comunicar o resultado devolvido pela tool de cotação; ele MUST NOT
calcular, estimar ou inferir um preço por conta própria em nenhuma circunstância,
incluindo quando a `/quote` falhar ou estiver indisponível.

#### Scenario: Cotação bem-sucedida
- **WHEN** a chamada à `/quote` retorna 200 com o prêmio calculado
- **THEN** o sistema apresenta ao lead exatamente o valor devolvido pela API, sem
  arredondamento ou ajuste feito pelo modelo de linguagem

#### Scenario: Falha total da API de cotação
- **WHEN** todas as tentativas de chamada à `/quote` falham
- **THEN** o sistema informa ao lead que não foi possível cotar no momento e aciona o
  handoff, sem apresentar nenhum valor numérico de prêmio

### Requirement: Comunicação das regras de negócio da cotação
Ao apresentar uma cotação bem-sucedida, o sistema SHALL informar ao lead a carência de
30 dias para as coberturas de roubo e furto, contada da data de início da vigência.
Quando a resposta da `/quote` incluir `primeiro_pagamento_pro_rata`, o sistema SHALL
comunicar o valor pro-rata do primeiro pagamento e esclarecer que os meses seguintes são
integrais. Quando o multiplicador de região for maior que 1.0, o sistema SHALL informar
que houve agravo por região de forma transparente.

#### Scenario: Vigência não inicia no dia 1
- **WHEN** a `/quote` devolve o campo `primeiro_pagamento_pro_rata`
- **THEN** o sistema informa ao lead o valor proporcional do primeiro pagamento e deixa
  claro que os pagamentos seguintes serão do valor integral

#### Scenario: CEP em região de agravo
- **WHEN** a cotação retorna um multiplicador de região maior que 1.0
- **THEN** o sistema comunica ao lead que o valor inclui um agravo por região, sem
  omitir essa informação na apresentação do preço

#### Scenario: Toda cotação apresentada menciona a carência
- **WHEN** o sistema apresenta qualquer cotação bem-sucedida ao lead
- **THEN** a mensagem inclui a informação de carência de 30 dias para roubo e furto

### Requirement: Recusa por regra de negócio comunicada com transparência
O sistema SHALL comunicar ao lead, de forma empática, o motivo real de qualquer recusa
de cotação por regra de negócio (idade acima do limite ou veículo além da idade
aceita) devolvida pela `/quote`, e MUST NOT apresentar essa recusa como uma
indisponibilidade técnica ou sistema fora do ar.

#### Scenario: Recusa por idade acima do limite
- **WHEN** a `/quote` retorna 422 com corpo `{"error": "cotacao_recusada", "motivo":
  "Idade acima do limite de aceitacao (75 anos)."}`
- **THEN** o sistema comunica ao lead que a apólice não pode ser emitida por conta do
  limite de idade, sem tentar nova cotação e sem mencionar falha de sistema

#### Scenario: Recusa por idade do veículo
- **WHEN** a `/quote` retorna 422 com corpo `{"error": "cotacao_recusada", "motivo":
  "Veiculo com mais de 20 anos nao e aceito."}`
- **THEN** o sistema comunica ao lead que o veículo está fora da idade aceita pela
  seguradora, sem tentar nova cotação

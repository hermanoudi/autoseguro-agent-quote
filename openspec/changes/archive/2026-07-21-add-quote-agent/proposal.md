## Why

A AutoSeguro atende leads de seguro de veículo pelo WhatsApp hoje inteiramente por
vendedores humanos, o que não escala. Precisamos de um agente que qualifique o lead,
cote um plano usando a API de cotação legada (`quote-service`, fornecida e instável de
propósito: 20% de falha, 10% de lentidão de 8s por chamada) e decida, por critério
explícito, quando resolve sozinho ou quando escala para um humano. Este é o entregável
do desafio técnico FDE / AI Engineer da Namastex; o critério de avaliação que mais pesa
é justamente o comportamento do agente quando a `/quote` falha.

## What Changes

- Novo serviço HTTP (`POST /message`) que recebe mensagens simulando um webhook de
  WhatsApp e mantém o estado da conversa por `conversation_id`
- Extração estruturada de dados do lead (idade, veículo/ano, CEP, plano, data de início)
  a partir de linguagem natural, sem o LLM jamais calcular ou estimar preço
- Camada única e resiliente de acesso à `/quote` (`QuoteClient`): timeout curto, retry
  com backoff e jitter, circuit breaker, e classificação correta de erro, incluindo os
  dois formatos distintos de `422` que a API devolve (regra de negócio vs. validação)
- Política de handoff determinística e testada (`HandoffPolicy`), separada do LLM
- Comunicação ao lead das regras de negócio que a API não explica sozinha (carência de
  30 dias para roubo/furto, pro-rata do primeiro mês, agravo de região)
- Log estruturado com `conversation_id`, `message_id` e `quote_attempt_id`
  correlacionáveis, sem dados sensíveis
- Redação de PII aplicada em log, prompt e qualquer uso do dataset de conversas
- Gerenciamento de credenciais via `.env`, nunca commitadas
- Script de demonstração que roda uma conversa completa ponta a ponta e grava o log de
  execução exigido pela entrega

## Capabilities

### New Capabilities
- `conversation-agent`: loop de conversa, qualificação do lead, extração estruturada de
  dados e apresentação da cotação, incluindo as regras de negócio (carência, pro-rata,
  agravo de região)
- `quote-resilience`: acesso resiliente à `/quote` via `QuoteClient`, com timeout, retry
  com backoff e jitter, circuit breaker e classificação de erro (transitório, regra de
  negócio, validação de payload)
- `handoff-policy`: decisão determinística e testada de quando escalar a conversa para
  um vendedor humano, com o pacote de contexto entregue no handoff
- `observability`: rastreabilidade ponta a ponta via `conversation_id`, `message_id` e
  `quote_attempt_id`, em log estruturado JSON
- `pii-protection`: redação de dados sensíveis (CPF, telefone, e-mail, placa, e redação
  parcial de CEP) aplicada em log, prompt e qualquer artefato derivado do dataset

### Modified Capabilities
(nenhuma; não existem specs anteriores neste projeto)

## Impact

- Código novo: serviço do agente (FastAPI, webhook), `QuoteClient`, `HandoffPolicy`,
  extrator de dados, redator de PII, logger estruturado, `ConversationStore`
- Integrações: `quote-service/` fornecido pelo desafio (`POST /quote`, `GET /planos`,
  não modificado); API do provedor de LLM (OpenAI), autenticada via `.env`
- Infraestrutura: novo serviço adicionado ao `docker-compose.yml` ao lado do
  `quote-api` já existente
- Dataset: `dataset/conversations.parquet` usado para eval set e observação de padrões,
  sempre passando pela redação de PII antes de qualquer persistência ou commit

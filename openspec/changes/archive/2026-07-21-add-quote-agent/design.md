## Context

Este é um sistema novo, construído para o desafio técnico FDE / AI Engineer da
Namastex, com prazo de aproximadamente 3 dias de relógio. Ele integra com um serviço já
fornecido e não modificável, o `quote-service` (`POST /quote`, `GET /planos`), que
simula uma API legada instável de propósito: 20% das chamadas falham (500/502/503) e
10% são lentas (8 segundos), sorteadas de forma independente por chamada. O
`docker-compose.yml` fornecido fixa essas taxas como literais, não aceitando override
via variável de ambiente do shell; para variar a taxa em teste é necessário rodar a API
fora do compose (`uv run uvicorn`) ou criar um `docker-compose.override.yml`.

As regras de precificação (faixas etárias, idade do veículo, agravo de região, carência,
pro-rata do primeiro mês) vivem em `quote-service/data/plans.json` e só são conhecidas
em runtime via `GET /planos`; não devem ser hardcoded no agente.

O critério de avaliação mais pesado é o comportamento do agente diante da instabilidade
da `/quote`. Os demais critérios (handoff explícito, rastreabilidade, cuidado com dados
sensíveis, legibilidade do código) também são avaliados individualmente.

## Goals / Non-Goals

**Goals:**
- Cotar corretamente no caminho feliz e se recuperar de falhas transitórias sem travar
  nem inventar preço
- Classificar corretamente os cinco formatos de erro conhecidos da `/quote`, incluindo
  os dois formatos distintos de 422
- Handoff decidido por código determinístico e testado, não pelo LLM
- Rastreabilidade completa por `conversation_id`, `message_id`, `quote_attempt_id`
- Nenhum dado sensível em log, prompt ou arquivo commitado
- Credenciais somente via `.env`, nunca commitadas

**Non-Goals:**
- Interface gráfica de chat
- Integração real com a API oficial do WhatsApp Business (o webhook é simulado)
- Autenticação multi-tenant, painel administrativo para vendedores
- Suporte a outros produtos de seguro além de veículo
- Emissão real de apólice ou processamento de pagamento

## Decisions

### Interface via webhook HTTP, não CLI
Um endpoint `POST /message` simula o webhook de WhatsApp e mantém o estado da conversa
por `conversation_id`. Alternativa considerada: CLI/simulador de terminal, mais simples
de implementar, mas menos fiel ao cenário real de atendimento (que é assíncrono e
stateful entre requisições). Optamos pelo webhook porque o `ConversationStore` que ele
exige é exatamente o componente que existiria em produção.

### Estado da conversa em `ConversationStore` simples
Armazenamento em memória mais um arquivo append-only JSONL por conversa, chaveado por
`conversation_id`. Alternativa considerada: banco de dados (Postgres/Redis), descartada
por ser desproporcional ao escopo de 3 dias e sem necessidade real de concorrência ou
persistência entre reinícios do processo para o desafio.

### `QuoteClient` como única porta de saída para a `/quote`
Toda resiliência (timeout, retry, backoff com jitter, circuit breaker, classificação de
erro) vive nesse componente. Alternativa considerada: deixar cada ponto de chamada tratar
seus próprios erros, descartada porque espalha lógica de resiliência e dificulta o teste
determinístico exigido pela avaliação.

### Classificação de erro pela forma do corpo, não só pelo status code
Os dois erros 422 (`cotacao_recusada` vs. validação Pydantic com `detail`) têm o mesmo
status code e semânticas opostas. A classificação SHALL inspecionar a presença da chave
`error` no corpo antes de decidir a ação. Essa distinção foi validada empiricamente
rodando a API localmente (ver `CLAUDE.md`).

### Timeout de cliente de aproximadamente 3 segundos
Definido por ser menor que os 8 segundos de lentidão simulada, e curto o suficiente para
permitir 2-3 tentativas dentro de um orçamento de latência aceitável para uma conversa de
WhatsApp. Alternativa considerada: aguardar o timeout padrão do httpx (sem limite
explícito), descartada porque deixaria a conversa travada por até 8 segundos em 10% das
chamadas.

### HandoffPolicy como função determinística separada do LLM
O LLM pode sinalizar intenção de handoff, mas uma tabela de gatilhos testável decide.
Alternativa considerada: deixar o LLM decidir via prompt, descartada porque o critério de
avaliação exige um critério "explícito e defensável", o que uma decisão implícita do
modelo não satisfaz de forma auditável.

### SDK OpenAI direto, sem framework de agente
Alternativa considerada: usar um framework de orquestração de agentes. Descartado para
manter o código legível para o avaliador e reduzir superfície de dependências em um
projeto de 3 dias; tool calling direto via SDK é suficiente para o escopo. A escolha do
provedor (OpenAI em vez de Anthropic) foi trocada durante a implementação por
disponibilidade de crédito de API para os testes reais ponta a ponta; o `LLMClient`
(`app/llm_client.py`) já isolava essa decisão atrás de um `Protocol`, então a troca ficou
restrita a `llm_client.py` e ao formato de tool schema/mensagens de tool-call em
`app/agent.py` (function-calling da OpenAI em vez do formato Anthropic).

### Redação de PII como processor único do structlog
Um módulo de redação aplicado como processor do logger estruturado, garantindo que a
redação aconteça por construção em toda mensagem de log, não por disciplina de quem
escreve cada linha de log. O mesmo módulo é reusado no pipeline de preparação do eval set
a partir do dataset.

### Credenciais via `.env`, nunca commitadas
`.env` no `.gitignore`; `.env.example` commitado documentando as variáveis necessárias
sem valores reais. Motivo: o repositório final é público, e expor uma chave de API real
seria falha de segurança grave e custo financeiro direto.

## Risks / Trade-offs

- [Confundir os dois formatos de 422] → Mitigação: teste nomeado para cada uma das seis
  classes de resposta da API, checklist dedicado na skill de resiliência do projeto
- [LLM alucinar preço em caso de falha total] → Mitigação: preço só existe se vier de uma
  resposta 200 real; teste de cenário com `QUOTE_FAILURE_RATE=1.0` validando ausência de
  preço na resposta
- [Vazamento de PII em log ou commit] → Mitigação: módulo único de redação, checagem
  manual de `git diff` antes de cada commit
- [Exposição de credencial de API no repositório público] → Mitigação: `.env` ignorado,
  `.env.example` documentado, checagem de `git status`/`diff` antes de cada commit
- [Estourar o timebox de 3 dias por excesso de processo] → Mitigação: timebox rígido para
  PRD e specs até o fim da manhã do Dia 1, cronograma diário já definido
- [Lentidão simulada travar a conversa] → Mitigação: timeout de cliente menor que a
  lentidão simulada, abortar e re-tentar em vez de esperar

## Migration Plan

Sistema novo, sem dados ou usuários em produção a migrar. Deploy via Docker Compose,
como serviço adicional (`quote-agent`) ao lado do `quote-api` já existente no
`docker-compose.yml`. Não há necessidade de rollback além de parar o novo serviço, já que
o `quote-service` não é modificado por este change.

## Open Questions

- Meta quantitativa de "conversas resolvidas sem handoff" (70% no PRD) é hipótese; será
  ajustada após rodar o eval set derivado do dataset de conversas
- Número exato de turnos sem progresso que aciona o gatilho de estagnação na
  `HandoffPolicy` será definido durante a implementação, observando o dataset de
  conversas reais
- Limite de falhas consecutivas para abrir o circuit breaker e o tempo de resfriamento
  serão definidos durante a implementação do `QuoteClient`, informados pelo teste com
  `QUOTE_SEED` fixo

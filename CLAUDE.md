# AutoSeguro — Agente de cotação (desafio FDE Namastex)

Agente de WhatsApp que qualifica leads de seguro auto, cota via API legada instável,
e decide quando escalar para um humano.

**Este repo é uma entrega de processo seletivo.** Otimize para: outro engenheiro
consegue ler, entender as decisões, e rodar. Clareza > esperteza.

## Stack

Python 3.11+ · FastAPI · httpx · tenacity · structlog · pytest · uv · Docker Compose.
SDK OpenAI direto — **sem framework de agente**.

Comandos: `uv run ...`, `docker compose up --build` (quote-service em :8000).

> ⚠️ **`docker-compose.yml` fixa `QUOTE_FAILURE_RATE`/`QUOTE_SLOW_RATE`/`QUOTE_SLOW_SECONDS`
> como literais** (não `${VAR}`). Variável de ambiente do shell **não sobrescreve**
> `docker compose up`. Para testar outras taxas (ex.: `QUOTE_FAILURE_RATE=1.0`), rode
> direto: `cd quote-service && QUOTE_FAILURE_RATE=1.0 uv run uvicorn app.main:app --port 8000`
> — ou crie um `docker-compose.override.yml`.

## Layout

- `quote-service/` — **API mock fornecida pelo desafio. NÃO MODIFICAR.**
- `dataset/conversations.parquet` — ~2.500 conversas sintéticas (1 linha = 1 mensagem)
- `PLANO.md` — plano de execução e decisões (documento de trabalho)

## Regras invioláveis

1. **O LLM nunca calcula nem estima preço.** Ele extrai parâmetros e comunica o que a
   tool retornou. Preço só existe se veio de uma resposta 200 da `/quote`. Sem exceção.
2. **Nenhum PII bruto em log, prompt de sistema ou disco.** Ver skill `pii-safety`.
3. **Handoff é código, não prompt.** Uma policy determinística e testada decide. O LLM
   pode sinalizar intenção; quem decide é a função.
4. **Toda chamada à `/quote` passa pelo `QuoteClient`.** Resiliência mora numa camada só.
5. Não editar nada dentro de `quote-service/`.

## Domínio — regras de `quote-service/data/plans.json`

Estão em arquivo de config e são fáceis de perder. O agente precisa **comunicá-las ao lead**:

- **Carência de 30 dias** para `roubo` e `furto`, contada da data de início da vigência.
- **Pro-rata do primeiro mês** quando `data_inicio` não é dia 1. A API só devolve
  `primeiro_pagamento_pro_rata` nesse caso; meses seguintes são integrais.
- **Agravo de 1.30** para CEP com prefixo `07`, `08`, `21`, `26`, `59`.
- Planos: `essencial` (119.90), `completo` (209.90), `premium` (339.90).
- **Recusas por regra:** idade > 75 anos; veículo com mais de 20 anos.
  Idade do veículo = `ano_atual - veiculo_ano`.

Fonte da verdade em runtime: `GET /planos`. Não hardcode valores — leia da API.

## A `/quote` é instável de propósito

20% de falha, 10% de lentidão (8s), sorteados **por chamada, independentemente**.
Tratar isso bem é o critério que mais pesa na avaliação. Ver skill `quote-api-resilience`.

Resumo da taxonomia de erro — **classificar errado aqui é o erro mais grave do projeto**:

| Status | Significado | Ação |
|---|---|---|
| `500` `502` `503` | Transitório | Retry com backoff |
| `422 cotacao_recusada` | **Regra de negócio** (idade/veículo) | Resposta empática. **Nunca retry, nunca "sistema fora do ar"** |
| `422` (`detail: [...]`, sem `error`) | **Validação do Pydantic** (campo faltando/tipo errado) | Corrigir extração, não re-tentar cego — **é um 422 diferente do de cima, mesmo status, formato distinto** |
| `400 payload_invalido` | Extração nossa errada (erro capturado dentro de `cotar()`) | Corrigir dados, não re-tentar cego |
| timeout | Chamada lenta | Abortar em ~3s e re-tentar (nunca esperar os 8s) |

> Validado empiricamente (2026-07-20): rodando a API direto (`uv run uvicorn`, fora do
> `docker compose up`), confirmei que os dois `422` têm corpo diferente — o de regra de
> negócio vem `{"error":"cotacao_recusada","motivo":...}`, o de payload inválido vem
> `{"detail":[{"type":"missing","loc":[...],"msg":...}]}` (formato padrão do FastAPI).
> O `QuoteClient` precisa distinguir pela **forma do corpo**, não só pelo status code.

## Critérios de avaliação (o que o entrevistador olha)

1. Funciona ponta a ponta 2. **Comportamento quando a `/quote` falha** 3. Critério de
handoff explícito e defensável 4. Rastreabilidade (id + status por mensagem/cotação)
5. Cuidado com dados sensíveis 6. Código legível e decisões documentadas

Todo trabalho deve se justificar contra um desses itens.

## Rastreabilidade

Todo evento carrega `conversation_id`; mensagens têm `message_id`; tentativas de cotação
têm `quote_attempt_id` + `attempt_no` + `status` + `latency_ms`. Log estruturado JSON.

## Processo

Spec-driven via **OpenSpec** (`openspec/`), com timebox: specs não podem consumir mais que
a manhã do Dia 1. TDD obrigatório nas partes determinísticas — `QuoteClient`,
`HandoffPolicy`, extração de dados, redação de PII. O loop conversacional se valida
pelo eval set, não por unit test.

PRD e specs devem alimentar o README final — a seção "decisões e porquês" é critério de
avaliação, então nada de documento descartável.

---
name: quote-api-resilience
description: Use when writing, reviewing or testing any code that calls the /quote API — the error taxonomy, retry policy, circuit breaker and deterministic failure testing for the intentionally-flaky legacy quote service. Triggers on QuoteClient, retry, timeout, circuit breaker, tenacity, httpx, 500/502/503, 422 cotacao_recusada, QUOTE_SEED, QUOTE_FAILURE_RATE.
---

# Resiliência da `/quote`

A `/quote` simula um sistema legado. `quote-service/app/main.py` sorteia **por chamada**,
de forma independente:

- `QUOTE_FAILURE_RATE` (default `0.20`) → devolve `500`, `502` ou `503`
- `QUOTE_SLOW_RATE` (default `0.10`) → dorme `QUOTE_SLOW_SECONDS` (default `8`)
- `QUOTE_SEED` → fixa o RNG, tornando a sequência de falhas reproduzível

Como os sorteios são independentes, **retry é genuinamente eficaz**: 20% de falha cai para
~0,8% em 3 tentativas. Isso justifica a política abaixo — cite esse número no README.

## 1. Classifique o erro antes de reagir

Esta é a decisão que mais separa candidatos. Nunca trate tudo como "API caiu".

| Resposta | Classe | Ação | Mensagem ao lead |
|---|---|---|---|
| `200` | sucesso | usar valores | apresenta cotação + carência + pro-rata |
| `500` `502` `503` | **transitório** | retry com backoff | nada (invisível) |
| timeout do cliente | **transitório** | abortar e retry | nada (invisível) |
| `422` com `{"error":"cotacao_recusada","motivo":...}` | **regra de negócio** | **não retry** | recusa empática com o motivo real |
| `422` com `{"detail":[{"type":"missing"/"...", ...}]}` | **validação Pydantic** — campo faltando/tipo errado | corrigir extração, não retry cego | pedir o dado faltante/inválido |
| `400 payload_invalido` (`{"error":"payload_invalido","detalhe":...}`) | **bug nosso** — erro capturado dentro de `cotar()` | corrigir extração, não retry cego | pedir o dado faltante/inválido |

⚠️ **Há dois formatos de `422` com o mesmo status code e semânticas opostas.** Confirmado
empiricamente (2026-07-20): pedir cotação sem `idade` retorna `422` mas com corpo
`{"detail":[{"type":"missing","loc":["body","idade"],"msg":"Field required",...}]}` —
esse é o Pydantic validando o `QuoteRequest` **antes** de chegar em `cotar()`, e é
estruturalmente idêntico a qualquer outro erro de validação do FastAPI. Já uma recusa de
negócio (idade > 75, veículo > 20 anos) retorna `422` com `{"error":"cotacao_recusada",
"motivo":"..."}`. **Classifique pela presença da chave `error` no corpo, nunca só pelo
status code** — tratar todo `422` como "recusa de negócio" faz o cliente engolir silenciosamente
bugs de extração; tratar todo `422` como "erro nosso" faz o agente re-tentar uma recusa que
nunca vai mudar.

Erros a evitar, em ordem de gravidade:

1. Re-tentar um `422 cotacao_recusada` — recusa por idade/veículo não melhora com insistência.
2. Dizer "sistema fora do ar" num `422 cotacao_recusada` — é um "não" legítimo da seguradora,
   mentir aqui destrói a confiança do lead e é uma falha de produto, não de infra.
3. Tratar `422` de validação Pydantic como recusa de negócio (ou vice-versa) — são o mesmo
   status code, corpos incompatíveis, ações opostas.
4. Esperar os 8s da chamada lenta em vez de abortar e re-tentar.
5. Inventar ou estimar preço quando tudo falha.

## 2. Política

- **Timeout de 3s** por tentativa. Precisa ser menor que `QUOTE_SLOW_SECONDS` (8s) —
  senão a chamada lenta consome o orçamento inteiro de latência da conversa.
- **3 tentativas**, backoff exponencial **com jitter** (0.5s, 1s, 2s ± jitter).
- **Circuit breaker**: após N falhas consecutivas, abre e para de tentar por um período.
  Evita fazer o lead esperar por um serviço comprovadamente morto.
- **Pré-validação local**: recusas por idade (>75) e veículo (>20 anos) são deriváveis das
  regras de `GET /planos`. Valide antes de chamar — economiza a chamada e responde na hora.
- **Esgotou tudo**: nunca invente número. Informe a indisponibilidade com honestidade,
  preserve os dados coletados e acione a `HandoffPolicy` com o contexto completo.

## 3. Teste determinístico (obrigatório)

Sistema não determinístico não é desculpa para não testar. Três alavancas:

⚠️ **`docker-compose.yml` fixa os valores de ambiente como literais**
(`QUOTE_FAILURE_RATE: "0.20"`, não `${QUOTE_FAILURE_RATE:-0.20}`). Prefixar a variável
antes de `docker compose up` **não tem efeito** — confirmado empiricamente rodando
`docker compose exec quote-api env` e vendo o valor do compose, não o do shell. Para variar
a taxa, rode a API direto (bypassando o compose) ou crie um `docker-compose.override.yml`:

```bash
# funciona — bypassa o compose inteiramente
cd quote-service
QUOTE_FAILURE_RATE=1.0 QUOTE_SLOW_RATE=0.0 uv run uvicorn app.main:app --port 8000

# NÃO funciona — docker-compose.yml ignora a env var do shell
QUOTE_FAILURE_RATE=1.0 docker compose up   # sobe com 0.20 mesmo assim
```

```bash
# falha total — prova o caminho de degradação e handoff
QUOTE_FAILURE_RATE=1.0 QUOTE_SLOW_RATE=0.0 uv run uvicorn app.main:app --port 8000

# caminho feliz garantido — testes de contrato e de cálculo
QUOTE_FAILURE_RATE=0.0 QUOTE_SLOW_RATE=0.0 uv run uvicorn app.main:app --port 8000

# sequência de falhas reproduzível — prova que o retry recupera
QUOTE_SEED=42 uv run uvicorn app.main:app --port 8000
```

Reproducibilidade do `QUOTE_SEED` **confirmada empiricamente**: duas execuções independentes
com `QUOTE_SEED=42` e a mesma sequência de 10 chamadas produziram o mesmo padrão de status
(`200 502 200 500 200 200 502 500 200 200` nas duas). Use isso para gravar o log de execução
da entrega de forma reprodutível.

Confirmado também: a chamada **lenta não é uma falha** — o processo dorme
`QUOTE_SLOW_SECONDS` e depois **sucede** (`200`) normalmente. Não existe timeout nativo da
API; o timeout é inteiramente uma decisão do cliente. Sem um timeout configurado no
`QuoteClient`, uma chamada lenta consome os 8s inteiros e trava a conversa — não falha, só demora.

Para unit tests do `QuoteClient`, não suba a API: use um transport fake do `httpx`
(`httpx.MockTransport`) e roteirize as respostas. Cada linha da tabela de taxonomia da
seção 1 deve ter **um teste nomeado** — é a evidência de que a classificação é intencional.

Reduza `QUOTE_SLOW_SECONDS` nos testes para não deixar a suíte lenta.

## 4. Rastreabilidade

Toda tentativa emite um evento estruturado com `quote_attempt_id`, `conversation_id`,
`attempt_no`, `status`, `error_class`, `latency_ms`. É isso que responde ao critério
"dá pra rastrear o que aconteceu?" — e o que torna o log de execução da entrega convincente.

## Checklist antes de dar por pronto

- [ ] As 6 classes de resposta têm teste nomeado (inclui os dois formatos de `422`)
- [ ] `QuoteClient` distingue os dois `422` pela chave `error` no corpo, não só pelo status
- [ ] Timeout < `QUOTE_SLOW_SECONDS`
- [ ] Backoff tem jitter
- [ ] `422 cotacao_recusada` não passa pelo retry (teste que prova isso)
- [ ] Cenário `QUOTE_FAILURE_RATE=1.0` termina em handoff, não em exceção nem em preço inventado
- [ ] Nenhum preço aparece em resposta ao lead sem ter vindo de um `200`

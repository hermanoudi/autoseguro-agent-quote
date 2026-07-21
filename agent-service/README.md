# AutoSeguro — Agente de cotação (agent-service)

Agente de WhatsApp (simulado via webhook HTTP) que qualifica leads de seguro de
veículo, cota via a `/quote` do `quote-service` (instável de propósito) e decide,
por critério determinístico, quando resolve sozinho ou encaminha para um humano.

Este documento cobre a solução deste desafio (`add-quote-agent` no OpenSpec). O PRD
está em `docs/challenge.prd`; as specs formais em
`openspec/changes/add-quote-agent/specs/`; as decisões técnicas detalhadas em
`openspec/changes/add-quote-agent/design.md`.

## Como rodar

```bash
cp .env.example .env
# preencha OPENAI_API_KEY no .env

docker compose up --build
# quote-service em :8000, agent-service em :8001
```

```bash
curl -X POST localhost:8001/message -H 'content-type: application/json' \
  -d '{"conversation_id":"conv_demo","text":"Oi, queria fazer um seguro pro meu carro"}'
```

Sem Docker:

```bash
cd quote-service && uv run uvicorn app.main:app --port 8000 &
cd agent-service && uv run uvicorn app.main:app --port 8001
```

### Testes

```bash
cd agent-service
uv sync --group dev
uv run pytest              # suíte rápida (mocks, sem rede) — 91 testes
uv run pytest -m integration  # sobe o quote-service real como subprocesso — 2 testes
```

## Arquitetura

```
POST /message (webhook estilo WhatsApp)
      │
      ▼
ConversationStore ──────► JSONL append-only (PII redigida antes de gravar)
      │  (estado em memória por conversation_id)
      ▼
handle_message (app/agent.py)
      │
      ├─► extraction.py ──── extração determinística (idade, ano, CEP, plano, data)
      ├─► HandoffPolicy ──── gatilhos determinísticos (checados antes e depois da cotação)
      ├─► LLMClient ───────── SDK OpenAI, tool calling (cotar_seguro)
      └─► QuoteClient ─────── único ponto de acesso à /quote: timeout, retry+jitter,
                               circuit breaker, classificação de erro
                               │
                               ▼
                         quote-service (fornecido, não modificado)
```

Componentes, com o arquivo onde vivem:

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Webhook | `app/main.py` | recebe a mensagem, persiste, delega, loga |
| `ConversationStore` | `app/store.py` | estado por `conversation_id`, JSONL redigido |
| Extração | `app/extraction.py` | regex/heurística determinística, sem LLM |
| `QuoteClient` | `app/quote_client.py` | toda resiliência da `/quote` |
| `HandoffPolicy` | `app/handoff.py` | gatilhos determinísticos de handoff |
| Núcleo do agente | `app/agent.py` | orquestra tudo, tool-calling, guarda anti-alucinação |
| PII | `app/pii.py` | redação, usada em log, store e prompt |
| Observabilidade | `app/observability.py` | log estruturado JSON, processor de PII ligado |

## Decisões e porquês

### O LLM nunca calcula preço
O modelo só pode citar um valor de prêmio que veio literalmente do resultado da tool
`cotar_seguro` — quem chama a `/quote` de verdade é sempre o `QuoteClient`, nunca o
modelo. Como defesa adicional (o modelo pode, em tese, ignorar a instrução do system
prompt), há uma guarda em código: se a resposta final do LLM contém um padrão de preço
(`R$\s*\d`) sem que uma cotação real tenha sido bem-sucedida nesta rodada, a resposta é
substituída por uma mensagem segura antes de chegar ao lead (`app/agent.py`, testado em
`tests/test_agent.py::test_guarda_defensiva_bloqueia_preco_nao_verificado`).

### Tabela de planos e regras vêm de `GET /planos`, nunca hardcodadas
O `system prompt` e o schema da tool `cotar_seguro` são montados em runtime a partir da
resposta de `GET /planos` (`app/agent.py:_build_system_prompt`, `_build_tool`) — o enum
de `plano_id` e a redação da carência são derivados da API, não de um texto fixo no
código. **Achado de auditoria corrigido nesta sessão**: a primeira versão do prompt
citava "carência de 30 dias" como texto fixo; se `plans.json` mudasse esse número, o
agente diria um valor errado sem nenhum erro aparente. Reescrito para instruir o modelo
a usar o `carencia.dias` que veio no resultado real da tool. Validado contra a API real
(subprocesso), não só contra um mock, em
`tests/test_quote_client_integration.py::test_planos_le_a_tabela_real_da_api_nao_hardcoded`.

### Extração determinística antes do LLM
`app/extraction.py` reconhece idade, ano do veículo, CEP, plano e data de início via
regex, sem chamar o modelo. Isso reduz custo e latência para os casos comuns, e — mais
importante — evita que o texto bruto do lead (que pode conter CPF/telefone/e-mail)
precise ir para o prompt só para extrair um número. Validado contra o dataset real do
desafio: **100% de acerto de idade e ano do veículo em uma amostra de 25 conversas**
(`scripts/eval_extraction.py`). Ressalva: a amostra é pequena e as mensagens do dataset
têm um padrão relativamente regular ("tenho 35 anos", "Toyota Corolla 2008"); com mais
tempo, valeria ampliar a amostra e medir contra parágrafos mais ambíguos.

### Minimização de dados no prompt do LLM
O texto do lead entra no histórico de mensagens do LLM **sempre redigido**
(`app/pii.py:redact`) — CPF, telefone, e-mail e placa nunca chegam ao prompt. Os campos
necessários para cotar (idade, ano do veículo, CEP completo, plano, data de início) vão
como estão, porque são necessários para o modelo popular a chamada da tool
corretamente; a spec `pii-protection` documenta essa distinção. Testado em
`tests/test_agent.py::test_prompt_minimiza_pii_do_lead`.

### Classificação de erro pela forma do corpo, não só pelo status code
A `/quote` devolve dois formatos de `422` com semânticas opostas: recusa de regra de
negócio (`{"error": "cotacao_recusada", ...}`) e erro de validação do Pydantic
(`{"detail": [...]}`). Confirmado empiricamente rodando a API localmente (ver
`CLAUDE.md`). O `QuoteClient` distingue pela chave `error` no corpo — nunca retry na
recusa de negócio, nunca "sistema fora do ar" nesse caso.

### Retry com backoff e jitter, timeout de 3s, circuit breaker
A falha é sorteada por chamada, independentemente (20% de falha, 10% de lentidão de 8s).
Isso torna o retry genuinamente eficaz: 3 tentativas derrubam ~20% de falha para
~0,8%. Timeout de cliente de 3s (menor que os 8s simulados) evita que uma chamada
lenta trave a conversa — a chamada é abortada e re-tentada, nunca esperada até o fim.
Circuit breaker abre após falhas transitórias consecutivas e rejeita novas tentativas
sem tocar a rede enquanto aberto. Validado com testes de integração reais
(`tests/test_quote_client_integration.py`, subindo o `quote-service` como subprocesso
com `QUOTE_FAILURE_RATE=1.0` e com `QUOTE_SEED=42` para provar reprodutibilidade).

> `docker-compose.yml` fixa as taxas de falha como literais — para variar a taxa em
> teste/demo, rode o `quote-service` direto via `uv run uvicorn`, não via
> `docker compose up` (ver aviso em `CLAUDE.md`).

### Handoff é código, não prompt
`app/handoff.py` é uma função pura, sem I/O, com um teste nomeado por gatilho:
pedido explícito de humano, esgotamento de tentativas de cotação (circuit breaker
aberto ou falha transitória esgotada), recusa de regra de negócio contestada pelo lead,
estagnação na coleta de dados (N turnos sem dado novo) e dado inconsistente após
correções repetidas. O LLM nunca decide sozinho — só o texto do lead e o outcome da
cotação alimentam a função, que devolve `should_handoff` + o motivo. O gatilho de
pedido explícito é checado **antes** de chamar o LLM (evita uma chamada desnecessária e
garante resposta determinística).

### Estado em memória + JSONL redigido
`ConversationStore` guarda o estado em memória (fonte de verdade em runtime) e grava um
append-only JSONL por `conversation_id` como trilha de auditoria — com a redação de PII
aplicada automaticamente antes de qualquer gravação em disco (`redact_dict` chamado
dentro de `_append_jsonl`, não como responsabilidade de quem chama).

### Credenciais via `.env`
`OPENAI_API_KEY` e demais configurações nunca são commitadas. `.env.example`
documenta as variáveis necessárias; `.env` está no `.gitignore` (com exceção explícita
para `.env.example`, já que `.env.*` sozinho o esconderia também). Sem a chave
configurada, `POST /message` devolve `503` com uma mensagem explicando o que falta
(verificado em container real), em vez de um `500` cru com stack trace.

## Rastreabilidade

Todo evento de log carrega `conversation_id`; toda mensagem tem `message_id`; toda
tentativa de cotação tem `quote_attempt_id` + `attempt_no` + `status` + `latency_ms`,
em JSON estruturado (`app/observability.py`), com PII redigida por um processor do
structlog ligado ao pipeline por construção — não por disciplina de quem loga.

## Limitações conhecidas / o que eu faria com mais tempo

- **Validação conversacional completa com LLM real**: feita com uma `OPENAI_API_KEY`
  real contra os 25 casos do eval set (`scripts/eval_agent.py`) e os dois cenários de
  demonstração (`scripts/demo_conversa.py`, logs em `logs/`). Extração ficou em
  100%/100% (idade/ano do veículo) nos 25 casos. Achados e correções na seção
  "Validação com LLM real" abaixo.
- Extração determinística cobre um conjunto razoável de padrões, mas não é um NLU
  completo — casos ambíguos (ex.: "dia 15" sem mês/ano) dependeriam do LLM perguntar de
  volta, não testado em automação.
- **Eval set não é representativo de conversão para o critério "cotação concluída"**:
  as 25 conversas do dataset têm o vendedor humano original escolhendo o plano sem
  perguntar ao lead; nosso agente, por design, nunca infere o plano — então 0/25
  conversas replayed chegam a cotar (21/25 terminam em handoff por estagnação). Isso
  reflete a regra inviolável do agente sendo respeitada sob pressão, não um defeito;
  mas significa que o eval set mede bem extração e handoff, e mal a taxa de conversão
  fim-a-fim (para isso seria preciso um lead simulado por LLM que responde às perguntas
  do próprio agente, não um replay de falas históricas).
- O limiar do circuit breaker e o número de turnos de estagnação estão com defaults
  razoáveis, mas não foram calibrados contra tráfego real.
- Detecção de placa/CPF/telefone por regex tem ambiguidade inerente em números bare
  de 11 dígitos (CPF vs. celular) — documentado em `app/pii.py`.

### Validação com LLM real: dois achados corrigidos

Rodar o loop conversacional completo contra o eval set (não só a extração
determinística) expôs dois problemas que os testes com LLM fake não pegavam, porque
dependiam do comportamento real do modelo:

1. **Bug de extração**: `_extract_veiculo_ano` lia o ano de `data_inicio` como se fosse
   o ano do veículo quando os dois apareciam em mensagens diferentes (ex.: o lead diz
   "Corolla 2020" num turno e "pode começar dia 15/07/2026" no turno seguinte — o "2026"
   da data era capturado como `veiculo_ano`, sobrescrevendo o valor correto até uma
   tool call da LLM corrigir por acidente). Corrigido excluindo o span da data
   reconhecida do mesmo jeito que já se fazia para o span da idade; teste de regressão
   em `tests/test_extraction.py::test_nao_confunde_ano_da_data_inicio_com_ano_do_veiculo`.
2. **Confirmação de plano vaga aceita pela LLM**: num caso do eval set, o lead respondeu
   "qualquer coisa me chama" (uma frase vaga) e o modelo chamou a tool com
   `plano_id: essencial` mesmo assim — uma violação leve da regra "só cota com plano
   confirmado explicitamente" do system prompt original. Reforçado o prompt em
   `app/agent.py:_build_system_prompt` para listar explicitamente que respostas vagas
   ("qualquer um", "tanto faz", "pode ser") não contam como confirmação. Revalidado: o
   mesmo caso agora pede o nome do plano de novo em vez de assumir, e o caminho feliz
   (plano dito explicitamente) continua cotando normalmente. Como essa é uma regra
   aplicada via prompt (não uma guarda em código, ao contrário da guarda anti-preço),
   ela é validada pelo eval set, não por unit test — coerente com a decisão já
   documentada no `CLAUDE.md` de que "o loop conversacional se valida pelo eval set".

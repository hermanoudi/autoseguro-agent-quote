## 1. Scaffolding do projeto

- [x] 1.1 Criar estrutura do serviço do agente (ex.: `agent-service/`) com `pyproject.toml`,
      `Dockerfile` e dependências (fastapi, httpx, tenacity, structlog, pytest, openai sdk)
- [x] 1.2 Adicionar `agent-service` ao `docker-compose.yml`, ao lado do `quote-api` já
      existente, sem modificar nada dentro de `quote-service/`
- [x] 1.3 Criar `.env.example` documentando as variáveis necessárias (chave de API do
      provedor de LLM, URL do `quote-service`, etc.), sem valores reais
- [x] 1.4 Confirmar que `.env` está ignorado e `.env.example` não, conforme `.gitignore`

## 2. Redação de PII (pii-protection)

- [x] 2.1 Escrever testes para o módulo de redação cobrindo CPF, telefone, e-mail e placa
      (formato antigo e Mercosul) em variações de formato
- [x] 2.2 Implementar `redact(text)` e `redact_dict(obj)` até os testes passarem
- [x] 2.3 Escrever teste de redação parcial de CEP (preserva os 2 primeiros dígitos)
- [x] 2.4 Implementar a redação parcial de CEP
- [x] 2.5 Escrever teste de pseudonimização estável (hash determinístico com salt)
- [x] 2.6 Implementar a pseudonimização e ligar o módulo como processor do structlog
- [x] 2.7 Verificar que o prompt do LLM recebe apenas os campos necessários (idade, ano
      do veículo, CEP, plano, data de início), nunca CPF/e-mail/placa

## 3. QuoteClient e resiliência (quote-resilience)

- [x] 3.1 Escrever teste que garante que toda chamada à `/quote` passa por um único
      componente (`QuoteClient`)
- [x] 3.2 Escrever testes de classificação de erro para as 6 classes de resposta (200,
      500/502/503, timeout, 422 `cotacao_recusada`, 422 `detail`, 400 `payload_invalido`)
      usando `httpx.MockTransport`, sem subir a API real
- [x] 3.3 Implementar a classificação de erro no `QuoteClient` até os testes passarem,
      distinguindo os dois formatos de 422 pela chave `error` no corpo
- [x] 3.4 Escrever teste de timeout por tentativa (~3s, menor que os 8s simulados)
- [x] 3.5 Implementar o timeout por tentativa
- [x] 3.6 Escrever teste de retry com backoff exponencial e jitter para erros
      transitórios, e teste garantindo que 422 `cotacao_recusada` nunca é re-tentado
- [x] 3.7 Implementar retry com backoff e jitter (até 3 tentativas)
- [x] 3.8 Escrever teste de circuit breaker (abre após N falhas consecutivas, rejeita
      novas chamadas sem tentar rede enquanto aberto)
- [x] 3.9 Implementar o circuit breaker
- [x] 3.10 Escrever teste de integração contra o `quote-service` real com
      `QUOTE_FAILURE_RATE=1.0`, validando que nenhum preço aparece na resposta e que o
      chamador recebe sinal de falha para acionar handoff
- [x] 3.11 Escrever teste de integração com `QUOTE_SEED` fixo, validando reprodutibilidade
      da sequência de falha/sucesso

## 4. Estado da conversa e webhook

- [x] 4.1 Implementar `ConversationStore` (memória + append-only JSONL por
      `conversation_id`)
- [x] 4.2 Implementar o endpoint `POST /message` simulando o webhook de WhatsApp,
      recebendo `conversation_id` e mensagem, delegando ao núcleo do agente
- [x] 4.3 Escrever teste de integração garantindo que o estado persiste corretamente
      entre requisições da mesma conversa

## 5. Agente conversacional e extração (conversation-agent)

- [x] 5.1 Escrever testes de extração estruturada (idade, ano do veículo a partir de
      texto livre, CEP, plano, data de início) usando exemplos derivados do dataset
- [x] 5.2 Implementar a extração até os testes passarem
- [x] 5.3 Implementar o núcleo do agente com tool calling via SDK OpenAI direto,
      garantindo que o LLM só invoca a tool de cotação e nunca calcula preço
- [x] 5.4 Implementar a apresentação da cotação incluindo carência de 30 dias,
      pro-rata do primeiro mês (quando presente) e agravo de região (quando aplicável)
      (instruído no system prompt; verificado no cenário de sucesso do teste do agente)
- [x] 5.5 Implementar a comunicação empática de recusa por regra de negócio (422
      `cotacao_recusada`), sem retry e sem mensagem de indisponibilidade técnica
- [x] 5.6 Escrever teste garantindo que nenhuma resposta ao lead contém preço que não
      veio de uma resposta 200 real da `/quote` (inclui guarda defensiva contra o
      modelo citar preço sem cotação real bem-sucedida)

## 6. Política de handoff (handoff-policy)

- [x] 6.1 Escrever um teste nomeado para cada gatilho definido na spec (pedido
      explícito, recusa de regra, esgotamento de retries/circuit breaker aberto,
      estagnação de turnos, dado inconsistente após correções)
- [x] 6.2 Implementar a `HandoffPolicy` como função determinística até os testes
      passarem
- [x] 6.3 Implementar o pacote de contexto do handoff (dados coletados, motivo,
      histórico de tentativas de cotação)
- [x] 6.4 Integrar a `HandoffPolicy` ao núcleo do agente, com o LLM apenas sinalizando
      intenção quando aplicável (pedido de humano encurta o turno sem chamar o LLM;
      esgotamento de cotação é reavaliado após a tentativa)

## 7. Observabilidade (observability)

- [x] 7.1 Implementar o logger estruturado com `conversation_id`, `message_id`,
      `quote_attempt_id`, `attempt_no`, `status` e `latency_ms`
- [x] 7.2 Escrever teste garantindo que nenhum evento de log contém PII em texto puro
- [x] 7.3 Ligar o processor de redação de PII ao pipeline de log estruturado

## 8. Demonstração, eval set e entrega

- [x] 8.1 Preparar um eval set de 20 a 30 conversas do dataset, passando pela redação de
      PII, com extração e desfecho esperado anotados (25 casos, `eval/eval_set.jsonl`,
      via `scripts/build_eval_set.py`; verdade de referência tirada de
      `lead_idade_informada`/`veiculo_texto`, já estruturadas no dataset)
- [x] 8.2 Rodar o agente contra o eval set e ajustar extração/prompt conforme os
      resultados — feito com `OPENAI_API_KEY` real (`scripts/eval_agent.py`, roda o
      loop conversacional completo via HTTP contra os 25 casos). Dois achados reais:
      (1) bug de extração — `_extract_veiculo_ano` lia o ano de `data_inicio`
      (ex.: "15/07/2026") como se fosse ano do veículo quando os dois não apareciam na
      mesma mensagem; corrigido excluindo o span da data, com teste de regressão em
      `tests/test_extraction.py`; extração ficou em 100%/100% (idade/ano) nos 25 casos,
      antes e depois; (2) a LLM aceitou uma resposta vaga ("qualquer coisa me chama")
      como confirmação implícita de plano em 1 dos 25 casos — violação leve da regra
      "só cota com plano confirmado explicitamente". Reforçado o system prompt em
      `app/agent.py` para exigir que o lead cite o nome do plano; validado que o
      mesmo caso agora pede confirmação de novo em vez de assumir, e que o caminho
      feliz (plano dito explicitamente) ainda cota normalmente. Resultado esperado e
      correto do eval set: 0/25 conversas chegam a cotação via replay, porque nenhum
      lead do dataset nomeia um plano para o nosso agente (o vendedor humano original
      escolhia por conta própria — algo que a regra inviolável do agente proíbe); 21/25
      terminam em handoff por estagnação, o resto fica "active" sem dado suficiente.
      Ver `agent-service/README.md` (seção de limitações) para o detalhe
- [x] 8.3 Escrever o script de demonstração que roda uma conversa completa ponta a
      ponta e grava o log de execução (`scripts/demo_conversa.py`, pronto para rodar)
- [x] 8.4 Rodar o cenário de sucesso e gravar o log de execução correspondente —
      feito com `OPENAI_API_KEY` real (`agent-service/logs/demo_sucesso.jsonl`):
      cotação real (R$ 241,38/mês, plano completo), pro-rata correto (R$ 132,37 por
      17 dias), carência calculada certa (30 dias a partir de 15/07/2026 → 14/08/2026)
- [x] 8.5 Rodar o cenário de falha total (`QUOTE_FAILURE_RATE=1.0`) terminando em
      handoff e gravar o log de execução correspondente — feito
      (`agent-service/logs/demo_falha_total.jsonl`): 3 tentativas (502, 502, 500),
      todas classificadas como transitórias, handoff por
      `esgotamento_tentativas_cotacao`, nenhum preço na resposta final
- [x] 8.6 Escrever o README com instruções de execução e a seção de decisões de
      engenharia, alimentada pelo PRD, pelo design.md e pelas specs
      (`agent-service/README.md`)
- [x] 8.7 Checar `git status`/`git diff` antes do commit final para garantir ausência de
      PII e de credenciais nos artefatos versionados (verificado: sem `.env` na árvore,
      sem CPF/e-mail bruto nos arquivos novos, sem chave de API hardcoded — repetir
      esta checagem depois de rodar o demo, que vai gerar `agent-service/logs/`)

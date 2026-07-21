## ADDED Requirements

### Requirement: Ponto único de acesso à API de cotação
Toda chamada à `/quote` SHALL passar por um componente único (`QuoteClient`). Nenhum
outro ponto do sistema MUST chamar a `/quote` diretamente. Isso garante que a política
de resiliência viva em um único lugar, testável isoladamente.

#### Scenario: Cotação disparada pela conversa
- **WHEN** o agente precisa cotar um plano para o lead
- **THEN** a chamada HTTP à `/quote` é feita exclusivamente através do `QuoteClient`

### Requirement: Timeout por tentativa menor que a lentidão simulada
O `QuoteClient` SHALL aplicar um timeout de aproximadamente 3 segundos por tentativa de
chamada à `/quote`. Esse valor MUST ser menor que os 8 segundos de lentidão simulada
pela API, de forma que uma chamada lenta seja abortada e re-tentada em vez de aguardada
até o fim.

#### Scenario: Chamada lenta é abortada
- **WHEN** a `/quote` demora mais que o timeout configurado para responder
- **THEN** o `QuoteClient` aborta a tentativa antes dos 8 segundos e inicia uma nova
  tentativa, respeitando o limite total de tentativas

### Requirement: Retry com backoff exponencial e jitter para erros transitórios
O `QuoteClient` SHALL classificar como transitório qualquer resposta 500, 502, 503, ou
timeout do cliente, e SHALL tentar novamente até 3 tentativas no total, com backoff
exponencial e jitter entre elas.

#### Scenario: Falha transitória seguida de sucesso
- **WHEN** a primeira tentativa retorna 503 e a segunda tentativa retorna 200
- **THEN** o `QuoteClient` devolve o resultado da segunda tentativa ao chamador, sem
  expor a falha da primeira tentativa ao lead

#### Scenario: Todas as tentativas falham por erro transitório
- **WHEN** as 3 tentativas retornam 500, 502 ou 503, ou expiram por timeout
- **THEN** o `QuoteClient` reporta falha ao chamador sem apresentar preço algum, e o
  chamador aciona a política de handoff

### Requirement: Classificação correta dos dois formatos de erro 422
O `QuoteClient` SHALL distinguir dois tipos de resposta com status 422 pela forma do
corpo, nunca apenas pelo status code:
- Corpo contendo a chave `error` com valor `cotacao_recusada`: recusa por regra de
  negócio. O `QuoteClient` MUST NOT re-tentar essa chamada.
- Corpo contendo a chave `detail` como lista (formato padrão de validação do FastAPI):
  erro de payload inválido causado por extração incorreta dos dados. O `QuoteClient`
  MUST NOT re-tentar cegamente; o erro SHALL ser reportado ao chamador para correção da
  extração.

#### Scenario: Recusa de regra de negócio não é re-tentada
- **WHEN** a `/quote` retorna 422 com corpo `{"error": "cotacao_recusada", "motivo":
  "..."}`
- **THEN** o `QuoteClient` não faz nenhuma nova tentativa e repassa o motivo da recusa ao
  chamador

#### Scenario: Erro de validação de payload não é re-tentado cegamente
- **WHEN** a `/quote` retorna 422 com corpo `{"detail": [{"type": "missing", "loc": [...],
  "msg": "..."}]}`
- **THEN** o `QuoteClient` não re-tenta a chamada com os mesmos dados e reporta ao
  chamador que o payload precisa de correção antes de nova tentativa

### Requirement: Classificação do erro 400 de payload inválido
O `QuoteClient` SHALL tratar qualquer resposta 400 com corpo `{"error":
"payload_invalido", "detalhe": "..."}` como erro de extração de dados, não como falha
transitória, e MUST NOT re-tentar cegamente com os mesmos dados.

#### Scenario: Payload inválido detectado pela própria lógica de cotação
- **WHEN** a `/quote` retorna 400 com corpo `{"error": "payload_invalido", "detalhe":
  "..."}`
- **THEN** o `QuoteClient` reporta o erro ao chamador como problema de dados, sem
  re-tentar a mesma chamada

### Requirement: Circuit breaker após falhas consecutivas
O `QuoteClient` SHALL manter um circuit breaker que abre após um número configurável de
falhas transitórias consecutivas e, enquanto aberto, SHALL rejeitar novas tentativas de
chamada imediatamente, sem aguardar o timeout de rede, até que o período de
resfriamento se encerre.

#### Scenario: Circuit breaker abre após falhas consecutivas
- **WHEN** o número de falhas transitórias consecutivas atinge o limite configurado
- **THEN** novas chamadas à `/quote` são rejeitadas imediatamente pelo circuit breaker,
  sem nova tentativa de rede, e o chamador aciona a política de handoff

### Requirement: Nenhum preço inventado quando a cotação não pode ser obtida
O sistema SHALL informar a indisponibilidade ao lead de forma honesta sempre que o
`QuoteClient` esgotar as tentativas de retry ou o circuit breaker estiver aberto, e MUST
NOT apresentar nenhum valor de prêmio estimado, aproximado ou calculado fora da resposta
real da API.

#### Scenario: Indisponibilidade total da API de cotação
- **WHEN** `QUOTE_FAILURE_RATE` está configurado em 1.0 e todas as tentativas falham
- **THEN** o lead recebe uma mensagem de indisponibilidade honesta, sem nenhum preço na
  resposta, e a conversa é encaminhada para handoff

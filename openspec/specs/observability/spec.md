## Purpose

Garantir rastreabilidade ponta a ponta do sistema via identificadores de correlação
(`conversation_id`, `message_id`, `quote_attempt_id`) em log estruturado JSON, sem nunca
expor dados sensíveis, e prover um mecanismo reproduzível de demonstração que gera um
log de execução completo como evidência da entrega.

## Requirements

### Requirement: Identificadores de correlação em toda a conversa
Todo evento gerado pelo sistema SHALL carregar um `conversation_id`. Toda mensagem
trocada com o lead SHALL ter um `message_id` próprio. Toda tentativa de chamada à
`/quote` SHALL ter um `quote_attempt_id` próprio, distinto por tentativa, mesmo dentro
da mesma cotação.

#### Scenario: Conversa completa é rastreável
- **WHEN** uma conversa é conduzida do início ao fim, incluindo uma ou mais tentativas
  de cotação
- **THEN** é possível reconstruir toda a sequência de eventos filtrando apenas pelo
  `conversation_id`

#### Scenario: Cada tentativa de cotação tem identidade própria
- **WHEN** o `QuoteClient` faz mais de uma tentativa para a mesma cotação devido a retry
- **THEN** cada tentativa é registrada com um `quote_attempt_id` e um número de tentativa
  (`attempt_no`) distintos, mesmo pertencendo à mesma cotação lógica

### Requirement: Log estruturado com status e latência
Cada evento de tentativa de cotação SHALL ser registrado em log estruturado JSON contendo
no mínimo: `conversation_id`, `quote_attempt_id`, `attempt_no`, `status` (classe do
resultado: sucesso, transitório, recusa de negócio, payload inválido) e `latency_ms`.

#### Scenario: Tentativa bem-sucedida é registrada
- **WHEN** uma chamada à `/quote` retorna 200
- **THEN** o log estruturado registra o evento com status de sucesso e a latência
  medida da chamada

#### Scenario: Tentativa falha é registrada com sua classe de erro
- **WHEN** uma chamada à `/quote` falha por qualquer motivo (transitório, recusa de
  negócio, payload inválido)
- **THEN** o log estruturado registra o evento com a classe de erro correspondente e a
  latência medida, sem confundir as classes entre si

### Requirement: Logs não contêm dados sensíveis
Nenhum evento de log estruturado SHALL conter dados sensíveis em texto puro (CPF,
telefone, e-mail, placa). Esse requisito é satisfeito em conjunto com a capability
`pii-protection`.

#### Scenario: Log de uma tentativa de cotação não expõe PII
- **WHEN** um evento de log é emitido durante o processamento de uma conversa
- **THEN** nenhum campo do log contém CPF, telefone, e-mail ou placa em texto puro

### Requirement: Log de execução completa reproduzível para a entrega
O sistema SHALL prover um mecanismo (script de demonstração) que roda uma conversa
completa ponta a ponta e grava um log de execução legível, incluindo ao menos um cenário
de sucesso e um cenário de falha com handoff, adequado para ser versionado como
evidência da entrega.

#### Scenario: Execução da demonstração gera log completo
- **WHEN** o script de demonstração é executado
- **THEN** um arquivo de log é gravado contendo a conversa completa e os eventos
  estruturados de cada tentativa de cotação envolvida

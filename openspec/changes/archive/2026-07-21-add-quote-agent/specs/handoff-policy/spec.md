## ADDED Requirements

### Requirement: Handoff decidido por função determinística
A decisão de encaminhar uma conversa para um vendedor humano SHALL ser tomada por uma
função determinística (`HandoffPolicy`), não pelo modelo de linguagem. O LLM MAY sinalizar
intenção de handoff (por exemplo, detectar que o lead pediu um humano), mas a decisão
final SHALL ser sempre avaliada pela função, de forma auditável e testável.

#### Scenario: LLM sinaliza, a função decide
- **WHEN** o LLM identifica uma possível necessidade de handoff durante a conversa
- **THEN** o sinal é passado para a `HandoffPolicy`, que aplica os gatilhos
  determinísticos e decide se o handoff ocorre

### Requirement: Gatilhos explícitos de handoff
A `HandoffPolicy` SHALL escalar a conversa para um humano quando qualquer um dos
seguintes gatilhos ocorrer:
- o lead pede explicitamente para falar com uma pessoa;
- a `/quote` recusa a cotação por regra de negócio e o lead demonstra interesse em
  entender alternativas ou contestar;
- o circuit breaker do `QuoteClient` está aberto ou todas as tentativas de cotação se
  esgotaram sem sucesso;
- a conversa permanece sem progresso na coleta de dados por um número configurável de
  turnos;
- um dado informado pelo lead permanece inconsistente após duas tentativas de correção.

#### Scenario: Pedido explícito de humano
- **WHEN** o lead escreve uma mensagem pedindo para falar com uma pessoa ou atendente
- **THEN** a `HandoffPolicy` aciona o handoff imediatamente, independentemente do
  estágio da conversa

#### Scenario: Esgotamento de tentativas de cotação
- **WHEN** o `QuoteClient` reporta falha após esgotar retries ou com o circuit breaker
  aberto
- **THEN** a `HandoffPolicy` aciona o handoff, preservando os dados já coletados do lead

#### Scenario: Estagnação na coleta de dados
- **WHEN** o lead não fornece nenhum dado novo necessário para a cotação após N turnos
  consecutivos (valor configurável)
- **THEN** a `HandoffPolicy` aciona o handoff

#### Scenario: Dado inconsistente após correções
- **WHEN** o lead fornece um dado que permanece inconsistente ou não confiável após duas
  tentativas de correção guiada pelo agente
- **THEN** a `HandoffPolicy` aciona o handoff

### Requirement: Pacote de contexto no handoff
Todo handoff acionado SHALL gerar um pacote de contexto contendo os dados do lead já
coletados, o motivo específico do handoff e, quando aplicável, o histórico de tentativas
de cotação (`quote_attempt_id`, status, latência). O sistema MUST NOT encaminhar um
handoff sem esse pacote de contexto.

#### Scenario: Handoff com contexto completo
- **WHEN** qualquer gatilho de handoff é acionado
- **THEN** o evento de handoff registrado inclui os dados do lead coletados até o
  momento e o motivo específico do gatilho que o originou

### Requirement: HandoffPolicy é testável isoladamente
A `HandoffPolicy` SHALL ser implementada como função pura ou componente testável
isoladamente, sem dependência de chamada de rede ou de resposta do modelo de linguagem
para decidir, de forma que cada gatilho tenha cobertura de teste automatizado.

#### Scenario: Cada gatilho tem teste nomeado
- **WHEN** a suíte de testes automatizados é executada
- **THEN** existe pelo menos um teste nomeado cobrindo cada um dos gatilhos definidos
  para a `HandoffPolicy`

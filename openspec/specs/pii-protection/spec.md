## Purpose

Aplicar redação de dados sensíveis (CPF, telefone, e-mail, placa, nome, e redação
parcial de CEP) através de um único módulo reutilizado em todas as bordas de saída do
sistema — log estruturado, transcrição de conversa persistida, prompt enviado ao LLM e
qualquer artefato derivado do dataset de conversas — para que nenhum dado pessoal em
texto puro vaze para disco, prompt ou log.

## Requirements

### Requirement: Redação de PII em uma camada única
O sistema SHALL aplicar a redação de dados sensíveis (CPF, telefone, e-mail, placa,
nome) através de um único módulo reutilizado em todas as bordas de saída: log
estruturado, transcrição de conversa persistida, prompt enviado ao LLM e qualquer
arquivo derivado do dataset de conversas. Nenhuma borda de saída MUST redigir PII por
lógica duplicada ou ad-hoc.

#### Scenario: Mesmo módulo usado em log e no pipeline do dataset
- **WHEN** um texto passa pelo log do agente ou pelo pipeline de preparação do eval set
  a partir do dataset
- **THEN** ambos aplicam a redação através do mesmo módulo de PII

### Requirement: Detecção tolerante a formatos variados
O módulo de redação SHALL reconhecer CPF, telefone, e-mail e placa (formato antigo
`ABC-1234` e Mercosul `ABC1D23`) mesmo quando aparecem soltos em texto livre, em
formatos variados (com ou sem pontuação, com ou sem espaços).

#### Scenario: CPF em formatos diferentes é redigido
- **WHEN** o texto contém um CPF no formato `123.456.789-00` ou `12345678900`
- **THEN** ambas as ocorrências são detectadas e redigidas

#### Scenario: Placa em formato antigo ou Mercosul é redigida
- **WHEN** o texto contém uma placa no formato `ABC-1234` ou `ABC1D23`
- **THEN** ambas as ocorrências são detectadas e redigidas

### Requirement: Redação parcial do CEP
O CEP SHALL ter seus dois primeiros dígitos preservados (necessários para o cálculo do
agravo de região) e o restante redigido, em vez de ser removido por completo.

#### Scenario: CEP preserva o prefixo de região
- **WHEN** o CEP `01310-100` passa pelo módulo de redação
- **THEN** o resultado preserva os dois primeiros dígitos (`01`) e redige o restante

### Requirement: Minimização de dados no prompt do LLM
O prompt enviado ao LLM SHALL conter apenas os dados estritamente necessários para
qualificar e cotar (idade, ano do veículo, CEP, plano desejado, data de início). CPF,
e-mail e placa MUST NOT ser incluídos no prompt quando não forem necessários para a
cotação.

#### Scenario: Lead informa CPF espontaneamente
- **WHEN** o lead envia o CPF numa mensagem, mesmo sem ser solicitado
- **THEN** o CPF não é incluído no prompt enviado ao LLM para as etapas de extração e
  conversa

### Requirement: Pseudonimização estável quando houver necessidade de correlação
O sistema SHALL usar um identificador pseudonimizado estável (hash determinístico com
salt) sempre que precisar correlacionar um mesmo lead entre eventos, nunca o valor
original em texto puro.

#### Scenario: Correlação de eventos do mesmo lead sem expor o dado original
- **WHEN** o sistema precisa referenciar o mesmo lead em mais de um evento de log
- **THEN** o identificador usado é um pseudônimo estável derivado por hash, não o dado
  pessoal original

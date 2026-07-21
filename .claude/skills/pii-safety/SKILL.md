---
name: pii-safety
description: Use when reading the conversations dataset, writing logs or transcripts, building prompts, or committing example output — the PII detection and redaction rules for this repo. Triggers on parquet, dataset, conversations, log, transcript, CPF, telefone, email, placa, CEP, redaction, LGPD, dados sensíveis.
---

# Proteção de dados sensíveis

"Cuidado com dados sensíveis" é um dos seis critérios de avaliação. O dataset é sintético
(`dataset/DICIONARIO.md`), mas o desafio pede explicitamente que seja tratado como se fosse
real — e o agente vai processar dados de lead de verdade em produção.

O sinal que o avaliador procura: **redação sistemática numa camada única**, não `# TODO: mask`
espalhado. Um módulo, testado, aplicado em todas as bordas de saída.

## Regra

Nenhum PII bruto pode sair do processo. Bordas onde a redação é obrigatória:

- log estruturado (arquivo e stdout)
- transcript de conversa persistido, incluindo o log de execução da entrega
- prompt enviado ao LLM — **minimize**: o modelo precisa de idade, ano do veículo, CEP e
  plano. Não precisa de CPF, e-mail nem placa. O que não é necessário não entra no prompt.
- qualquer arquivo commitado (fixtures, exemplos no README, eval set)
- mensagens de erro e stack traces

## O que redigir

Os dados aparecem **soltos no meio do texto livre, em formatos variados** — o dicionário
avisa isso. Regex tem que tolerar as variações:

| Dado | Variações no dataset |
|---|---|
| CPF | `123.456.789-00`, `12345678900`, com espaços |
| Telefone | `(11) 91234-5678`, `11912345678`, `+55 11 91234-5678` |
| E-mail | formato padrão |
| Placa | `ABC-1234` (antiga) e `ABC1D23` (Mercosul) |
| Nome | `sender_name` é campo estruturado — pseudonimizar |
| CEP | **caso especial, ver abaixo** |

### CEP: redação parcial, não total

O CEP é necessário para cotar (o agravo de região usa os **2 primeiros dígitos**). Mascarar
por completo quebra a rastreabilidade da cotação. Guarde `01310-100` → `01*******`:
preserva o que determina o preço, descarta o que localiza a pessoa.

Essa distinção — redigir o que não é necessário, preservar o mínimo que o negócio exige —
é o argumento de minimização de dados que vale escrever no README.

## Implementação

- Um módulo (ex.: `pii.py`) com `redact(text) -> str` e `redact_dict(obj) -> dict`.
- Um **processor do structlog**, para que a redação seja automática e não dependa de alguém
  lembrar de chamar. Defesa por construção, não por disciplina.
- Pseudonimização estável quando precisar correlacionar: hash determinístico com salt
  (`lead_a1b2c3`), nunca o valor original.
- Testes com todas as variações de formato da tabela acima.
- Mesmo módulo usado no pipeline do dataset e no runtime do agente.

## Ao usar o dataset

- Redija **na leitura**, antes de qualquer coisa tocar o dado.
- Nunca commite trechos brutos do parquet como fixture — commite a versão redigida.
- Se gerar eval set ou few-shot a partir das conversas, o conteúdo passa pela redação antes.
- `message_type` `image`/`audio`/`document` só tem marcador (`[documento] CNH_frente.pdf`) —
  sem transcrição. Nomes de arquivo podem vazar contexto sensível; trate o marcador como texto.

## Checklist

- [ ] Módulo único, com testes por formato
- [ ] Ligado como processor do structlog
- [ ] Prompt do LLM recebe só o necessário para cotar
- [ ] CEP com redação parcial (2 dígitos preservados), justificada no README
- [ ] `grep` por CPF/e-mail/placa nos logs e fixtures commitados não retorna nada
- [ ] README explica a decisão de minimização

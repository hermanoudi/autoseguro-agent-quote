"""Núcleo conversacional do agente.

O LLM nunca calcula preço (regra inviolável do projeto): ele só pode citar um valor
que veio literalmente do resultado real do `QuoteClient`. A tool `cotar_seguro` é
executada por código, não pelo modelo — o modelo apenas decide QUANDO chamá-la e
fornece os parâmetros; quem fala com a `/quote` é sempre o `QuoteClient`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.extraction import extract_lead_data
from app.handoff import HandoffContext, build_handoff_context_package, evaluate_handoff
from app.llm_client import LLMClient
from app.pii import redact
from app.quote_client import QuoteAttempt, QuoteClient
from app.store import ConversationStore

def _build_system_prompt(planos_data: dict) -> str:
    """Monta o system prompt com os nomes de plano e a observação de carência lidos
    de `GET /planos` em runtime — nunca hardcoda dias de carência, agravo ou preço.
    `plans.json` é a fonte da verdade; se mudar, o prompt muda junto, sem deploy novo.
    """
    plano_ids = ", ".join(p["id"] for p in planos_data["planos"])
    carencia_obs = planos_data["regras"]["carencia"]["_obs"]

    return f"""\
Voce e um agente de vendas da AutoSeguro, atendendo um lead pelo WhatsApp. Seu \
objetivo e qualificar o lead e cotar um plano de seguro de veiculo usando a tool \
`cotar_seguro`.

Regras inegociaveis:
- Voce NUNCA calcula, estima ou arredonda um preco, nem nenhum outro numero da \
cotacao (dias de carencia, multiplicadores, valores). Todo numero que voce citar tem \
que ter vindo literalmente do resultado da tool `cotar_seguro` nesta conversa — nunca \
de memoria ou suposicao sua, mesmo que pareca obvio.
- Antes de chamar a tool, confirme com o lead: idade, ano do veiculo e o plano \
desejado (opcoes atuais: {plano_ids}). So considere o plano confirmado se o lead \
citar um dos nomes das opcoes explicitamente (ex.: "quero o completo") ou concordar \
claramente com um plano que voce sugeriu por nome. Respostas vagas como "qualquer \
um", "tanto faz", "pode ser" ou "qualquer coisa me chama" NAO contam como \
confirmacao de plano — nesse caso pergunte de novo, oferecendo as opcoes por nome. \
CEP e data de inicio sao opcionais, mas pergunte por eles se o lead nao mencionar.
- Quando a tool devolver uma cotacao com sucesso (`resultado: sucesso`), sua resposta \
SEMPRE menciona a carencia usando o valor exato do campo `carencia.dias` do \
resultado (nao assuma um numero fixo de dias — {carencia_obs}) para as coberturas \
listadas em `carencia.coberturas`. Se o resultado tiver `primeiro_pagamento_pro_rata`, \
explique o valor proporcional do primeiro pagamento (campo `valor_primeiro_pagamento`) \
e deixe claro que os meses seguintes sao integrais. Se `multiplicadores.regiao` for \
maior que 1.0, informe que houve agravo por regiao.
- Quando a tool devolver uma recusa de regra de negocio (`resultado: recusado`), \
explique o motivo com empatia, usando o texto do campo `motivo`. Nunca diga que o \
sistema esta fora do ar, nunca sugira tentar de novo.
- Quando a tool indicar indisponibilidade (`resultado: indisponivel`), informe \
honestamente que nao foi possivel cotar agora e que alguem da equipe vai dar \
continuidade. Nunca apresente nenhum valor numerico de premio nesse caso.
- Seja direto e cordial. Uma pergunta por vez.
"""


def _build_tool(planos_data: dict) -> dict:
    """Schema da tool (formato function-calling da OpenAI) com o enum de `plano_id`
    lido de `GET /planos`, não hardcodado."""
    plano_ids = [p["id"] for p in planos_data["planos"]]
    return {
        "type": "function",
        "function": {
            "name": "cotar_seguro",
            "description": (
                "Solicita uma cotacao real de seguro auto para a seguradora. So chame quando "
                "idade, ano do veiculo e plano desejado ja estiverem confirmados com o lead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plano_id": {"type": "string", "enum": plano_ids},
                    "idade": {"type": "integer"},
                    "veiculo_ano": {"type": "integer"},
                    "cep": {"type": "string"},
                    "data_inicio": {"type": "string", "description": "YYYY-MM-DD, opcional"},
                },
                "required": ["plano_id", "idade", "veiculo_ano"],
            },
        },
    }



_PRECO_NAO_VERIFICADO_RE = re.compile(r"R\$\s*\d")
_RESPOSTA_SEGURA_PADRAO = (
    "Ainda nao consegui confirmar um valor com a seguradora agora. Vou continuar "
    "tentando e te aviso assim que tiver a cotacao certinha."
)
_RESPOSTA_HANDOFF_PADRAO = (
    "Entendido. Vou te colocar em contato com um de nossos consultores para "
    "continuar o atendimento."
)

_MAX_TOOL_ROUNDTRIPS = 1


@dataclass
class AgentTurnResult:
    reply: str
    quote_attempts: list[QuoteAttempt] = field(default_factory=list)
    had_successful_quote: bool = False
    refused: bool = False
    unavailable: bool = False
    handoff: bool = False
    handoff_reason: str | None = None
    handoff_context: dict | None = None


def _build_tool_result_payload(outcome) -> dict:
    if outcome.success:
        return {"resultado": "sucesso", **outcome.data}
    if outcome.error_class == "business_refusal":
        return {"resultado": "recusado", "motivo": outcome.motivo}
    return {"resultado": "indisponivel", "detalhe": outcome.error_class}


def _history_as_messages(store: ConversationStore, conversation_id: str) -> list[dict]:
    state = store.get_or_create(conversation_id)
    messages = []
    for msg in state.messages:
        role = "user" if msg.role == "lead" else "assistant"
        text = redact(msg.text) if msg.role == "lead" else msg.text
        messages.append({"role": role, "content": text})
    return messages


async def handle_message(
    conversation_id: str,
    text: str,
    store: ConversationStore,
    quote_client: QuoteClient,
    llm_client: LLMClient,
) -> AgentTurnResult:
    extracted = extract_lead_data(text)
    if extracted:
        store.update_lead_data(conversation_id, **extracted)
    store.mark_turn_progress(conversation_id, had_new_data=bool(extracted))
    state = store.get_or_create(conversation_id)

    # Gatilhos que independem de uma tentativa de cotacao nesta rodada (pedido
    # explicito de humano, estagnacao, correcoes repetidas): avaliados antes de
    # gastar uma chamada ao LLM.
    early_decision = evaluate_handoff(
        HandoffContext(
            lead_message=text,
            lead_data=state.lead_data,
            turns_without_progress=state.turns_without_progress,
            correction_attempts=state.field_correction_counts,
        )
    )
    if early_decision.should_handoff:
        store.set_status(conversation_id, "handoff")
        package = build_handoff_context_package(
            conversation_id, state.lead_data, early_decision.reason
        )
        return AgentTurnResult(
            reply=_RESPOSTA_HANDOFF_PADRAO,
            handoff=True,
            handoff_reason=early_decision.reason,
            handoff_context=package,
        )

    planos_data = await quote_client.planos()
    system_prompt = _build_system_prompt(planos_data)
    tool = _build_tool(planos_data)

    messages = _history_as_messages(store, conversation_id)

    response = await llm_client.create(system=system_prompt, messages=messages, tools=[tool])

    quote_attempts: list[QuoteAttempt] = []
    had_successful_quote = False
    refused = False
    unavailable = False
    outcome = None

    tool_use = response.tool_use()
    roundtrips = 0
    while tool_use is not None and roundtrips < _MAX_TOOL_ROUNDTRIPS:
        roundtrips += 1
        params = dict(tool_use.input)
        store.update_lead_data(conversation_id, **params)

        outcome = await quote_client.cotar(params)
        quote_attempts.extend(outcome.attempts)
        had_successful_quote = outcome.success
        refused = outcome.error_class == "business_refusal"
        unavailable = outcome.error_class in ("transient", "circuit_open")

        tool_result_payload = _build_tool_result_payload(outcome)
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_use.id,
                        "type": "function",
                        "function": {
                            "name": tool_use.name,
                            "arguments": json.dumps(tool_use.input, ensure_ascii=False),
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_use.id,
                "content": json.dumps(tool_result_payload, ensure_ascii=False),
            }
        )
        response = await llm_client.create(system=system_prompt, messages=messages, tools=[tool])
        tool_use = response.tool_use()

    reply = response.first_text() or ""

    if not had_successful_quote and _PRECO_NAO_VERIFICADO_RE.search(reply):
        reply = _RESPOSTA_SEGURA_PADRAO

    handoff = False
    handoff_reason = None
    handoff_context = None
    if outcome is not None:
        state = store.get_or_create(conversation_id)
        decision = evaluate_handoff(
            HandoffContext(
                lead_message=text,
                lead_data=state.lead_data,
                quote_outcome=outcome,
                turns_without_progress=state.turns_without_progress,
                correction_attempts=state.field_correction_counts,
            )
        )
        if decision.should_handoff:
            store.set_status(conversation_id, "handoff")
            handoff = True
            handoff_reason = decision.reason
            handoff_context = build_handoff_context_package(
                conversation_id, state.lead_data, decision.reason, quote_attempts
            )

    return AgentTurnResult(
        reply=reply,
        quote_attempts=quote_attempts,
        had_successful_quote=had_successful_quote,
        refused=refused,
        unavailable=unavailable,
        handoff=handoff,
        handoff_reason=handoff_reason,
        handoff_context=handoff_context,
    )

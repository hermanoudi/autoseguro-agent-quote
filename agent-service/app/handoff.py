"""Política de handoff: função determinística e testável, separada do LLM.

O LLM pode sinalizar intenção (ex.: perceber que o lead está insatisfeito), mas quem
decide se a conversa vai para um humano é sempre esta função — auditável e coberta por
teste nomeado para cada gatilho, como pede a spec `handoff-policy`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.quote_client import QuoteAttempt, QuoteOutcome

_HUMAN_REQUEST_KEYWORDS = [
    "atendente",
    "pessoa de verdade",
    "falar com uma pessoa",
    "falar com alguem",
    "quero um humano",
    "humano de verdade",
]

_CONTESTATION_KEYWORDS = [
    "mas ",
    "nao concordo",
    "não concordo",
    "tem como",
    "sera que",
    "será que",
    "pode fazer algo",
    "por que nao",
    "por que não",
]

DEFAULT_STAGNATION_THRESHOLD = 3
DEFAULT_CORRECTION_THRESHOLD = 2


@dataclass
class HandoffContext:
    lead_message: str
    lead_data: dict
    quote_outcome: QuoteOutcome | None = None
    turns_without_progress: int = 0
    correction_attempts: dict = field(default_factory=dict)
    stagnation_threshold: int = DEFAULT_STAGNATION_THRESHOLD
    correction_threshold: int = DEFAULT_CORRECTION_THRESHOLD


@dataclass
class HandoffDecision:
    should_handoff: bool
    reason: str | None = None


def _lead_requested_human(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _HUMAN_REQUEST_KEYWORDS)


def _lead_contests(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _CONTESTATION_KEYWORDS)


def evaluate_handoff(ctx: HandoffContext) -> HandoffDecision:
    """Avalia os gatilhos em ordem de prioridade e devolve a primeira decisão positiva."""
    if _lead_requested_human(ctx.lead_message):
        return HandoffDecision(True, "pedido_explicito_de_humano")

    if ctx.quote_outcome is not None and not ctx.quote_outcome.success:
        if ctx.quote_outcome.error_class in ("transient", "circuit_open"):
            return HandoffDecision(True, "esgotamento_tentativas_cotacao")
        if ctx.quote_outcome.error_class == "business_refusal" and _lead_contests(ctx.lead_message):
            return HandoffDecision(True, "recusa_de_regra_contestada")

    if ctx.turns_without_progress >= ctx.stagnation_threshold:
        return HandoffDecision(True, "estagnacao_na_coleta_de_dados")

    for count in ctx.correction_attempts.values():
        if count > ctx.correction_threshold:
            return HandoffDecision(True, "dado_inconsistente_apos_correcoes")

    return HandoffDecision(False)


def build_handoff_context_package(
    conversation_id: str,
    lead_data: dict,
    reason: str | None,
    quote_attempts: list[QuoteAttempt] | None = None,
) -> dict:
    return {
        "conversation_id": conversation_id,
        "motivo": reason,
        "dados_coletados": dict(lead_data),
        "tentativas_cotacao": [asdict(attempt) for attempt in (quote_attempts or [])],
    }

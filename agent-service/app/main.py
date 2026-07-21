"""Webhook HTTP que simula o canal do WhatsApp. Mantém o estado da conversa por
`conversation_id` via `ConversationStore` e delega o processamento ao núcleo do agente.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.agent import handle_message
from app.llm_client import AnthropicLLMClient, LLMClient
from app.observability import configure_logging, get_logger, log_handoff, log_message, log_quote_attempt
from app.quote_client import QuoteClient
from app.store import ConversationStore

DATA_DIR = Path(os.getenv("AGENT_DATA_DIR", "data/conversations"))
QUOTE_SERVICE_URL = os.getenv("QUOTE_SERVICE_URL", "http://localhost:8000")

configure_logging()
_logger = get_logger()

app = FastAPI(title="AutoSeguro Quote Agent")

_store = ConversationStore(storage_dir=DATA_DIR)
_quote_client = QuoteClient(base_url=QUOTE_SERVICE_URL)
_llm_client: LLMClient | None = None


def get_store() -> ConversationStore:
    return _store


def get_quote_client() -> QuoteClient:
    return _quote_client


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail=(
                    "ANTHROPIC_API_KEY nao configurada. Copie .env.example para .env "
                    "e preencha a chave antes de conversar com o agente."
                ),
            )
        _llm_client = AnthropicLLMClient()
    return _llm_client


class MessageRequest(BaseModel):
    conversation_id: str
    text: str


class MessageResponse(BaseModel):
    conversation_id: str
    message_id: str
    reply: str
    status: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/message", response_model=MessageResponse)
async def post_message(
    req: MessageRequest,
    store: ConversationStore = Depends(get_store),
    quote_client: QuoteClient = Depends(get_quote_client),
    llm_client: LLMClient = Depends(get_llm_client),
) -> MessageResponse:
    lead_message = store.add_message(req.conversation_id, role="lead", text=req.text)
    log_message(_logger, conversation_id=req.conversation_id, message_id=lead_message.message_id, role="lead")

    result = await handle_message(
        conversation_id=req.conversation_id,
        text=req.text,
        store=store,
        quote_client=quote_client,
        llm_client=llm_client,
    )

    for attempt in result.quote_attempts:
        log_quote_attempt(_logger, conversation_id=req.conversation_id, attempt=attempt)
    if result.handoff:
        log_handoff(_logger, conversation_id=req.conversation_id, reason=result.handoff_reason)

    agent_message = store.add_message(req.conversation_id, role="agent", text=result.reply)
    log_message(
        _logger, conversation_id=req.conversation_id, message_id=agent_message.message_id, role="agent"
    )
    state = store.get_or_create(req.conversation_id)

    return MessageResponse(
        conversation_id=req.conversation_id,
        message_id=agent_message.message_id,
        reply=result.reply,
        status=state.status,
    )

"""Log estruturado JSON com rastreabilidade por `conversation_id`, `message_id` e
`quote_attempt_id`. O processor de redação de PII (`app.pii.structlog_pii_processor`)
fica ligado ao pipeline por construção — nenhum evento sai sem passar por ele.
"""
from __future__ import annotations

import logging

import structlog

from app.pii import structlog_pii_processor
from app.quote_client import QuoteAttempt


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog_pii_processor,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger():
    return structlog.get_logger()


def log_quote_attempt(logger, conversation_id: str, attempt: QuoteAttempt, **extra) -> None:
    logger.info(
        "quote_attempt",
        conversation_id=conversation_id,
        quote_attempt_id=attempt.quote_attempt_id,
        attempt_no=attempt.attempt_no,
        status=attempt.status,
        latency_ms=round(attempt.latency_ms, 2),
        http_status=attempt.http_status,
        **extra,
    )


def log_message(logger, conversation_id: str, message_id: str, role: str) -> None:
    logger.info("message", conversation_id=conversation_id, message_id=message_id, role=role)


def log_handoff(logger, conversation_id: str, reason: str | None) -> None:
    logger.info("handoff", conversation_id=conversation_id, reason=reason)

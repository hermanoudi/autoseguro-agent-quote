"""Ponto único de acesso à `/quote`. Toda resiliência (timeout, retry com backoff e
jitter, circuit breaker, classificação de erro) vive aqui — nenhum outro módulo deve
chamar a `/quote` diretamente.

Classificação de erro (ver skill `quote-api-resilience` e CLAUDE.md):
- 200: sucesso
- 500/502/503/timeout: transitório, retry
- 422 com corpo `{"error": "cotacao_recusada", ...}`: regra de negócio, nunca retry
- 422 com corpo `{"detail": [...]}` (Pydantic): payload inválido, nunca retry cego
- 400 com corpo `{"error": "payload_invalido", ...}`: payload inválido, nunca retry cego
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter


@dataclass
class QuoteAttempt:
    quote_attempt_id: str
    attempt_no: int
    status: str  # "success" | "transient" | "business_refusal" | "invalid_payload"
    latency_ms: float
    http_status: int | None = None


@dataclass
class QuoteOutcome:
    success: bool
    data: dict | None = None
    error_class: str | None = None  # "transient" | "business_refusal" | "invalid_payload" | "circuit_open"
    motivo: str | None = None
    attempts: list[QuoteAttempt] = field(default_factory=list)


class _TransientQuoteError(Exception):
    pass


class _BusinessRefusal(Exception):
    def __init__(self, motivo: str | None):
        self.motivo = motivo


class _InvalidPayload(Exception):
    def __init__(self, detail):
        self.detail = detail


class QuoteClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
        max_attempts: int = 3,
        retry_wait_initial: float = 0.5,
        retry_wait_max: float = 4.0,
        breaker_threshold: int = 5,
        breaker_cooldown_seconds: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url or "", transport=transport, timeout=timeout_seconds
        )
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_wait_initial = retry_wait_initial
        self.retry_wait_max = retry_wait_max
        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown_seconds = breaker_cooldown_seconds
        self._consecutive_transient_failures = 0
        self._breaker_opened_at: float | None = None
        self._planos_cache: dict | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def planos(self) -> dict:
        """GET /planos — tabela de planos e regras. Fonte da verdade em runtime;
        quem consome isto nunca deve hardcodar plano_id, dias de carência, etc.
        Cacheado por instância (a tabela não muda no meio de uma conversa)."""
        if self._planos_cache is None:
            response = await self._client.get("/planos")
            response.raise_for_status()
            self._planos_cache = response.json()
        return self._planos_cache

    async def cotar(self, payload: dict) -> QuoteOutcome:
        if self._breaker_is_open():
            return QuoteOutcome(success=False, error_class="circuit_open", attempts=[])

        attempts: list[QuoteAttempt] = []
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential_jitter(initial=self.retry_wait_initial, max=self.retry_wait_max),
            retry=retry_if_exception_type(_TransientQuoteError),
            reraise=True,
        )
        try:
            data = await retrying(self._attempt_once, payload, attempts)
            return QuoteOutcome(success=True, data=data, attempts=attempts)
        except _BusinessRefusal as exc:
            return QuoteOutcome(
                success=False, error_class="business_refusal", motivo=exc.motivo, attempts=attempts
            )
        except _InvalidPayload as exc:
            return QuoteOutcome(
                success=False, error_class="invalid_payload", motivo=str(exc.detail), attempts=attempts
            )
        except _TransientQuoteError:
            return QuoteOutcome(success=False, error_class="transient", attempts=attempts)

    async def _attempt_once(self, payload: dict, attempts: list[QuoteAttempt]) -> dict:
        attempt_no = len(attempts) + 1
        attempt_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            response = await self._client.post("/quote", json=payload)
        except (httpx.TimeoutException, httpx.TransportError):
            latency_ms = (time.monotonic() - start) * 1000
            attempts.append(QuoteAttempt(attempt_id, attempt_no, "transient", latency_ms, None))
            self._on_transient_failure()
            raise _TransientQuoteError()

        latency_ms = (time.monotonic() - start) * 1000
        status = response.status_code

        if status == 200:
            attempts.append(QuoteAttempt(attempt_id, attempt_no, "success", latency_ms, status))
            self._on_reachable()
            return response.json()

        if status in (500, 502, 503):
            attempts.append(QuoteAttempt(attempt_id, attempt_no, "transient", latency_ms, status))
            self._on_transient_failure()
            raise _TransientQuoteError()

        if status == 422:
            body = response.json()
            if isinstance(body, dict) and body.get("error") == "cotacao_recusada":
                attempts.append(
                    QuoteAttempt(attempt_id, attempt_no, "business_refusal", latency_ms, status)
                )
                self._on_reachable()
                raise _BusinessRefusal(body.get("motivo"))
            attempts.append(QuoteAttempt(attempt_id, attempt_no, "invalid_payload", latency_ms, status))
            self._on_reachable()
            raise _InvalidPayload(body.get("detail") if isinstance(body, dict) else body)

        if status == 400:
            body = response.json()
            attempts.append(QuoteAttempt(attempt_id, attempt_no, "invalid_payload", latency_ms, status))
            self._on_reachable()
            detail = body.get("detalhe") or body.get("detail") if isinstance(body, dict) else body
            raise _InvalidPayload(detail)

        # status inesperado: nao trava, trata como transitorio e registra para investigacao
        attempts.append(QuoteAttempt(attempt_id, attempt_no, "transient", latency_ms, status))
        self._on_transient_failure()
        raise _TransientQuoteError()

    def _on_transient_failure(self) -> None:
        self._consecutive_transient_failures += 1
        if self._consecutive_transient_failures >= self.breaker_threshold:
            self._breaker_opened_at = time.monotonic()

    def _on_reachable(self) -> None:
        self._consecutive_transient_failures = 0
        self._breaker_opened_at = None

    def _breaker_is_open(self) -> bool:
        if self._breaker_opened_at is None:
            return False
        if time.monotonic() - self._breaker_opened_at >= self.breaker_cooldown_seconds:
            self._breaker_opened_at = None
            self._consecutive_transient_failures = 0
            return False
        return True

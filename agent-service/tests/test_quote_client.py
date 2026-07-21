import re
from pathlib import Path

import httpx
import pytest

from app.quote_client import QuoteClient

PAYLOAD = {"plano_id": "essencial", "idade": 35, "veiculo_ano": 2022}


def _client_for(handler, **kwargs) -> QuoteClient:
    transport = httpx.MockTransport(handler)
    return QuoteClient(
        base_url="http://quote-test",
        transport=transport,
        timeout_seconds=3.0,
        max_attempts=kwargs.get("max_attempts", 3),
        retry_wait_initial=0.001,
        retry_wait_max=0.005,
        breaker_threshold=kwargs.get("breaker_threshold", 5),
        breaker_cooldown_seconds=kwargs.get("breaker_cooldown_seconds", 30),
    )


class TestPontoUnicoDeAcesso:
    def test_nenhum_outro_modulo_chama_slash_quote_diretamente(self):
        """Busca literais de string Python ("/quote" ou '/quote'), nao mencoes em
        prosa/docstring (que usam crase, estilo Markdown, ex.: `/quote`)."""
        chamada_re = re.compile(r"""["']\/quote["']""")
        app_dir = Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in app_dir.rglob("*.py"):
            if path.name == "quote_client.py":
                continue
            text = path.read_text(encoding="utf-8")
            if chamada_re.search(text):
                offenders.append(str(path))
        assert offenders == [], f"chamada direta a /quote fora do QuoteClient: {offenders}"


class TestClassificacaoDeErro:
    @pytest.mark.asyncio
    async def test_sucesso_200(self):
        async def handler(request):
            return httpx.Response(200, json={"plano_id": "essencial", "premio_mensal": 119.9})

        client = _client_for(handler)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is True
        assert outcome.data["premio_mensal"] == 119.9
        assert outcome.attempts[-1].status == "success"

    @pytest.mark.asyncio
    async def test_500_e_transitorio(self):
        async def handler(request):
            return httpx.Response(500, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=1)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is False
        assert outcome.error_class == "transient"

    @pytest.mark.asyncio
    async def test_502_e_transitorio(self):
        async def handler(request):
            return httpx.Response(502, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=1)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.error_class == "transient"

    @pytest.mark.asyncio
    async def test_503_e_transitorio(self):
        async def handler(request):
            return httpx.Response(503, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=1)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.error_class == "transient"

    @pytest.mark.asyncio
    async def test_422_cotacao_recusada_e_regra_de_negocio(self):
        async def handler(request):
            return httpx.Response(
                422, json={"error": "cotacao_recusada", "motivo": "Idade acima do limite."}
            )

        client = _client_for(handler)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is False
        assert outcome.error_class == "business_refusal"
        assert outcome.motivo == "Idade acima do limite."
        assert len(outcome.attempts) == 1, "recusa de negocio nao pode ser re-tentada"

    @pytest.mark.asyncio
    async def test_422_validacao_pydantic_e_payload_invalido(self):
        async def handler(request):
            return httpx.Response(
                422,
                json={"detail": [{"type": "missing", "loc": ["body", "idade"], "msg": "Field required"}]},
            )

        client = _client_for(handler)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is False
        assert outcome.error_class == "invalid_payload"
        assert len(outcome.attempts) == 1, "payload invalido nao pode ser re-tentado cego"

    @pytest.mark.asyncio
    async def test_400_payload_invalido(self):
        async def handler(request):
            return httpx.Response(400, json={"error": "payload_invalido", "detalhe": "idade invalida"})

        client = _client_for(handler)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is False
        assert outcome.error_class == "invalid_payload"
        assert len(outcome.attempts) == 1

    @pytest.mark.asyncio
    async def test_timeout_e_transitorio(self):
        async def handler(request):
            raise httpx.TimeoutException("timed out", request=request)

        client = _client_for(handler, max_attempts=1)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.error_class == "transient"

    def test_timeout_configurado_e_menor_que_lentidao_simulada(self):
        client = QuoteClient(base_url="http://x", timeout_seconds=3.0)
        assert client.timeout_seconds == 3.0
        assert client.timeout_seconds < 8.0, "timeout deve ser menor que QUOTE_SLOW_SECONDS (8s)"


class TestRetryComBackoffEJitter:
    @pytest.mark.asyncio
    async def test_falha_transitoria_seguida_de_sucesso(self):
        calls = {"n": 0}

        async def handler(request):
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(503, json={"error": "upstream_unavailable"})
            return httpx.Response(200, json={"plano_id": "essencial", "premio_mensal": 119.9})

        client = _client_for(handler, max_attempts=3)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is True
        assert len(outcome.attempts) == 2
        assert outcome.attempts[0].status == "transient"
        assert outcome.attempts[1].status == "success"

    @pytest.mark.asyncio
    async def test_esgota_tentativas_apos_falhas_transitorias_persistentes(self):
        async def handler(request):
            return httpx.Response(503, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=3)
        outcome = await client.cotar(PAYLOAD)
        assert outcome.success is False
        assert outcome.error_class == "transient"
        assert len(outcome.attempts) == 3

    @pytest.mark.asyncio
    async def test_recusa_de_negocio_nunca_e_re_tentada_mesmo_com_max_attempts_alto(self):
        calls = {"n": 0}

        async def handler(request):
            calls["n"] += 1
            return httpx.Response(422, json={"error": "cotacao_recusada", "motivo": "..."})

        client = _client_for(handler, max_attempts=5)
        outcome = await client.cotar(PAYLOAD)
        assert calls["n"] == 1


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_abre_apos_falhas_consecutivas_e_rejeita_sem_tentar_rede(self):
        calls = {"n": 0}

        async def handler(request):
            calls["n"] += 1
            return httpx.Response(503, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=1, breaker_threshold=2)

        await client.cotar(PAYLOAD)  # 1a falha transitoria
        await client.cotar(PAYLOAD)  # 2a falha transitoria, atinge o limiar e abre

        calls_before_breaker = calls["n"]
        outcome = await client.cotar(PAYLOAD)  # deveria ser rejeitado sem chamar a rede

        assert outcome.success is False
        assert outcome.error_class == "circuit_open"
        assert outcome.attempts == []
        assert calls["n"] == calls_before_breaker, "circuit breaker aberto nao deve chamar a rede"

    @pytest.mark.asyncio
    async def test_sucesso_reseta_contador_de_falhas_consecutivas(self):
        calls = {"n": 0}

        async def handler(request):
            calls["n"] += 1
            if calls["n"] == 2:
                return httpx.Response(200, json={"plano_id": "essencial", "premio_mensal": 119.9})
            return httpx.Response(503, json={"error": "upstream_unavailable"})

        client = _client_for(handler, max_attempts=1, breaker_threshold=2)
        await client.cotar(PAYLOAD)  # falha 1
        await client.cotar(PAYLOAD)  # sucesso, reseta contador
        outcome = await client.cotar(PAYLOAD)  # falha 1 de novo, breaker ainda fechado
        assert outcome.error_class != "circuit_open"

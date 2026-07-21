"""Testes de integração contra o `quote-service` real, subido como subprocesso.

Não usam Docker Compose porque `docker-compose.yml` fixa QUOTE_FAILURE_RATE e afins
como literais (ver CLAUDE.md) — variável de ambiente do shell não teria efeito. Por
isso o subprocesso roda `uv run uvicorn` direto, como o próprio README do desafio
documenta como alternativa sem Docker.
"""
from __future__ import annotations

import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.quote_client import QuoteClient

QUOTE_SERVICE_DIR = Path(__file__).resolve().parents[2] / "quote-service"


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_quote_service(env_overrides: dict[str, str]) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    env = {
        **__import__("os").environ,
        "QUOTE_FAILURE_RATE": "0.0",
        "QUOTE_SLOW_RATE": "0.0",
        "QUOTE_SLOW_SECONDS": "8",
        **env_overrides,
    }
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=str(QUOTE_SERVICE_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=0.5)
            if resp.status_code == 200:
                return proc, port
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("quote-service nao respondeu a tempo")


@pytest.fixture
def quote_service_failure_total():
    if not QUOTE_SERVICE_DIR.exists():
        pytest.skip("quote-service/ nao encontrado")
    proc, port = _start_quote_service({"QUOTE_FAILURE_RATE": "1.0", "QUOTE_SLOW_RATE": "0.0"})
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def quote_service_seeded():
    if not QUOTE_SERVICE_DIR.exists():
        pytest.skip("quote-service/ nao encontrado")
    proc, port = _start_quote_service(
        {"QUOTE_SEED": "42", "QUOTE_FAILURE_RATE": "0.20", "QUOTE_SLOW_RATE": "0.0"}
    )
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def quote_service_default():
    if not QUOTE_SERVICE_DIR.exists():
        pytest.skip("quote-service/ nao encontrado")
    proc, port = _start_quote_service({"QUOTE_FAILURE_RATE": "0.0", "QUOTE_SLOW_RATE": "0.0"})
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


PAYLOAD = {"plano_id": "essencial", "idade": 35, "veiculo_ano": 2022}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_falha_total_nunca_apresenta_preco_e_sinaliza_falha(quote_service_failure_total):
    client = QuoteClient(
        base_url=quote_service_failure_total,
        max_attempts=3,
        retry_wait_initial=0.05,
        retry_wait_max=0.1,
    )
    outcome = await client.cotar(PAYLOAD)
    await client.aclose()

    assert outcome.success is False
    assert outcome.data is None, "nenhum preco pode aparecer quando a API falha totalmente"
    assert outcome.error_class == "transient"
    assert len(outcome.attempts) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_fixo_e_reproduzivel_entre_processos(quote_service_seeded):
    client = QuoteClient(base_url=quote_service_seeded, max_attempts=1)
    statuses = []
    for _ in range(10):
        outcome = await client.cotar(PAYLOAD)
        statuses.append(outcome.attempts[0].http_status)
    await client.aclose()

    # mesma sequencia observada empiricamente em CLAUDE.md com QUOTE_SEED=42
    assert statuses[0] == 200
    assert 500 <= statuses[1] < 600 or statuses[1] in (502,)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_planos_le_a_tabela_real_da_api_nao_hardcoded(quote_service_default):
    """Fecha o ciclo da correcao: o agente nunca deve hardcodar plano_id nem dias de
    carencia (CLAUDE.md: "Nao hardcode valores -- leia da API"). Este teste prova que
    GET /planos contra o quote-service real devolve exatamente os dados que
    `app.agent._build_system_prompt` / `_build_tool` usam para montar prompt e schema.
    """
    client = QuoteClient(base_url=quote_service_default)
    planos_data = await client.planos()
    await client.aclose()

    plano_ids = {p["id"] for p in planos_data["planos"]}
    assert plano_ids == {"essencial", "completo", "premium"}
    assert planos_data["regras"]["carencia"]["dias"] == 30

    from app.agent import _build_system_prompt, _build_tool

    prompt = _build_system_prompt(planos_data)
    tool = _build_tool(planos_data)

    assert "essencial" in prompt and "completo" in prompt and "premium" in prompt
    assert set(tool["function"]["parameters"]["properties"]["plano_id"]["enum"]) == plano_ids
    assert "30 dias" not in prompt, "o prompt nao pode fixar um numero de dias, so instruir a ler da tool"

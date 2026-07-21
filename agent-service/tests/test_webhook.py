import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm_client import LLMResponse, TextBlock
from app.main import app, get_llm_client, get_quote_client, get_store
from app.quote_client import QuoteClient
from app.store import ConversationStore


class ScriptedLLMClient:
    def __init__(self, replies):
        self._replies = list(replies)

    async def create(self, *, system, messages, tools):
        text = self._replies.pop(0) if self._replies else "Pode me dar mais detalhes?"
        return LLMResponse(content=[TextBlock(text=text)])


PLANOS_FIXTURE = {
    "moeda": "BRL",
    "planos": [
        {"id": "essencial", "nome": "Essencial", "base_mensal": 119.9},
        {"id": "completo", "nome": "Completo", "base_mensal": 209.9},
        {"id": "premium", "nome": "Premium", "base_mensal": 339.9},
    ],
    "regras": {
        "carencia": {
            "_obs": "Coberturas de roubo e furto so passam a valer apos a carencia.",
            "coberturas_com_carencia": ["roubo", "furto"],
            "dias": 30,
        }
    },
}


@pytest.fixture
def client(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)

    async def handler(request):
        if request.url.path == "/planos":
            return httpx.Response(200, json=PLANOS_FIXTURE)
        return httpx.Response(200, json={"plano_id": "essencial", "premio_mensal": 119.9})

    quote_client = QuoteClient(base_url="http://quote-test", transport=httpx.MockTransport(handler))
    llm_client = ScriptedLLMClient(["Ola! Qual sua idade?", "Entendido, e o ano do veiculo?"])

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_quote_client] = lambda: quote_client
    app.dependency_overrides[get_llm_client] = lambda: llm_client

    with TestClient(app) as test_client:
        yield test_client, store

    app.dependency_overrides.clear()


def test_health():
    with TestClient(app) as test_client:
        assert test_client.get("/health").json() == {"status": "ok"}


def test_message_retorna_resposta_do_agente(client):
    test_client, _store = client
    resp = test_client.post("/message", json={"conversation_id": "conv_1", "text": "oi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Ola! Qual sua idade?"
    assert body["conversation_id"] == "conv_1"
    assert body["status"] == "active"


def test_estado_persiste_entre_requisicoes_da_mesma_conversa(client):
    test_client, store = client
    test_client.post("/message", json={"conversation_id": "conv_1", "text": "oi, tenho 35 anos"})
    test_client.post("/message", json={"conversation_id": "conv_1", "text": "e um corolla 2020"})

    state = store.get_or_create("conv_1")
    assert len(state.messages) == 4  # 2 do lead + 2 do agente
    assert state.lead_data["idade"] == 35
    assert state.lead_data["veiculo_ano"] == 2020


def test_conversas_diferentes_nao_se_misturam(client):
    test_client, store = client
    test_client.post("/message", json={"conversation_id": "conv_a", "text": "tenho 35 anos"})
    test_client.post("/message", json={"conversation_id": "conv_b", "text": "tenho 50 anos"})

    assert store.get_or_create("conv_a").lead_data["idade"] == 35
    assert store.get_or_create("conv_b").lead_data["idade"] == 50


def test_sem_anthropic_api_key_retorna_erro_claro_nao_500_cru(monkeypatch):
    """Sem a dependency override do LLM (usa o get_llm_client real do main.py)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import app.main as main_module

    main_module._llm_client = None  # garante que vai tentar instanciar de novo

    with TestClient(app) as test_client:
        resp = test_client.post("/message", json={"conversation_id": "conv_x", "text": "oi"})

    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]

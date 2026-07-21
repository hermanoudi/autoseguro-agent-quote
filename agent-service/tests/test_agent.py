import httpx
import pytest

from app.agent import handle_message
from app.llm_client import LLMResponse, TextBlock, ToolUseBlock
from app.quote_client import QuoteClient
from app.store import ConversationStore


class FakeLLMClient:
    """Cliente fake: devolve respostas pre-programadas em sequencia e grava as
    chamadas recebidas, para testar a orquestracao sem rede nem ANTHROPIC_API_KEY."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return self._responses.pop(0)


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


def _with_planos(handler):
    """Envolve um handler de /quote para tambem responder GET /planos de verdade,
    como o agent.py exige (nunca hardcoda a tabela de planos)."""

    async def wrapped(request):
        if request.url.path == "/planos":
            return httpx.Response(200, json=PLANOS_FIXTURE)
        return await handler(request)

    return wrapped


def _quote_client_for(handler) -> QuoteClient:
    return QuoteClient(
        base_url="http://quote-test",
        transport=httpx.MockTransport(_with_planos(handler)),
        max_attempts=3,
        retry_wait_initial=0.001,
        retry_wait_max=0.005,
    )


async def _success_handler(request):
    return httpx.Response(
        200,
        json={
            "plano_id": "essencial",
            "premio_mensal": 119.9,
            "carencia": {"dias": 30, "coberturas": ["roubo", "furto"]},
            "multiplicadores": {"faixa_etaria": 1.0, "idade_veiculo": 1.0, "regiao": 1.0},
        },
    )


async def _refusal_handler(request):
    return httpx.Response(422, json={"error": "cotacao_recusada", "motivo": "Idade acima do limite."})


async def _unavailable_handler(request):
    return httpx.Response(503, json={"error": "upstream_unavailable"})


@pytest.mark.asyncio
async def test_sem_tool_use_apenas_repassa_o_texto(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="oi")
    llm = FakeLLMClient([LLMResponse(content=[TextBlock(text="Ola! Qual sua idade?")])])
    quote_client = _quote_client_for(_success_handler)

    result = await handle_message("conv_1", "oi", store, quote_client, llm)

    assert result.reply == "Ola! Qual sua idade?"
    assert result.quote_attempts == []
    assert result.had_successful_quote is False


@pytest.mark.asyncio
async def test_tool_use_com_sucesso_atualiza_lead_data_e_retorna_resposta_final(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="quero o essencial, 35 anos, corolla 2020")
    llm = FakeLLMClient(
        [
            LLMResponse(
                content=[
                    ToolUseBlock(
                        id="tool_1",
                        name="cotar_seguro",
                        input={"plano_id": "essencial", "idade": 35, "veiculo_ano": 2020},
                    )
                ]
            ),
            LLMResponse(
                content=[
                    TextBlock(
                        text="Sua cotacao ficou em R$ 119,90/mes. Vale lembrar da carencia de 30 dias "
                        "para roubo e furto."
                    )
                ]
            ),
        ]
    )
    quote_client = _quote_client_for(_success_handler)

    result = await handle_message(
        "conv_1", "quero o essencial, 35 anos, corolla 2020", store, quote_client, llm
    )

    assert result.had_successful_quote is True
    assert len(result.quote_attempts) == 1
    assert "119,90" in result.reply
    state = store.get_or_create("conv_1")
    assert state.lead_data["plano_id"] == "essencial"
    assert state.lead_data["idade"] == 35


@pytest.mark.asyncio
async def test_tool_use_com_recusa_de_negocio(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="quero o essencial, 80 anos, corolla 2020")
    llm = FakeLLMClient(
        [
            LLMResponse(
                content=[
                    ToolUseBlock(
                        id="tool_1",
                        name="cotar_seguro",
                        input={"plano_id": "essencial", "idade": 80, "veiculo_ano": 2020},
                    )
                ]
            ),
            LLMResponse(
                content=[
                    TextBlock(
                        text="Infelizmente nao consigo emitir a apolice por conta do limite de idade."
                    )
                ]
            ),
        ]
    )
    quote_client = _quote_client_for(_refusal_handler)

    result = await handle_message(
        "conv_1", "quero o essencial, 80 anos, corolla 2020", store, quote_client, llm
    )

    assert result.refused is True
    assert result.had_successful_quote is False
    assert "R$" not in result.reply


@pytest.mark.asyncio
async def test_tool_use_com_indisponibilidade(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="quero o essencial, 35 anos, corolla 2020")
    llm = FakeLLMClient(
        [
            LLMResponse(
                content=[
                    ToolUseBlock(
                        id="tool_1",
                        name="cotar_seguro",
                        input={"plano_id": "essencial", "idade": 35, "veiculo_ano": 2020},
                    )
                ]
            ),
            LLMResponse(
                content=[
                    TextBlock(text="Nao consegui cotar agora, mas vou continuar tentando.")
                ]
            ),
        ]
    )
    quote_client = _quote_client_for(_unavailable_handler)

    result = await handle_message(
        "conv_1", "quero o essencial, 35 anos, corolla 2020", store, quote_client, llm
    )

    assert result.unavailable is True
    assert result.had_successful_quote is False
    assert len(result.quote_attempts) == 3  # esgotou as 3 tentativas
    assert result.handoff is True
    assert result.handoff_reason == "esgotamento_tentativas_cotacao"
    assert store.get_or_create("conv_1").status == "handoff"


@pytest.mark.asyncio
async def test_pedido_explicito_de_humano_aciona_handoff_sem_chamar_o_llm(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="quero falar com um atendente")
    llm = FakeLLMClient([])  # nao deveria ser chamado
    quote_client = _quote_client_for(_success_handler)

    result = await handle_message(
        "conv_1", "quero falar com um atendente", store, quote_client, llm
    )

    assert result.handoff is True
    assert result.handoff_reason == "pedido_explicito_de_humano"
    assert llm.calls == []
    assert store.get_or_create("conv_1").status == "handoff"


@pytest.mark.asyncio
async def test_guarda_defensiva_bloqueia_preco_nao_verificado(tmp_path):
    """Mesmo se o modelo se comportar mal e citar um preco sem uma cotacao real
    bem-sucedida, o codigo substitui a resposta por uma mensagem segura."""
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="quero o essencial, 35 anos, corolla 2020")
    llm = FakeLLMClient(
        [
            LLMResponse(
                content=[
                    ToolUseBlock(
                        id="tool_1",
                        name="cotar_seguro",
                        input={"plano_id": "essencial", "idade": 35, "veiculo_ano": 2020},
                    )
                ]
            ),
            LLMResponse(content=[TextBlock(text="Fica R$ 199,90 por mes, pode confirmar?")]),
        ]
    )
    quote_client = _quote_client_for(_unavailable_handler)

    result = await handle_message(
        "conv_1", "quero o essencial, 35 anos, corolla 2020", store, quote_client, llm
    )

    assert "R$" not in result.reply
    assert result.had_successful_quote is False


@pytest.mark.asyncio
async def test_prompt_minimiza_pii_do_lead(tmp_path):
    """CPF/telefone/email/placa que o lead digitou nao podem chegar ao prompt do LLM."""
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message(
        "conv_1",
        role="lead",
        text="meu cpf e 123.456.789-00 e meu email lead@example.com, tenho 35 anos",
    )
    llm = FakeLLMClient([LLMResponse(content=[TextBlock(text="Qual o ano do seu veiculo?")])])
    quote_client = _quote_client_for(_success_handler)

    await handle_message(
        "conv_1",
        "meu cpf e 123.456.789-00 e meu email lead@example.com, tenho 35 anos",
        store,
        quote_client,
        llm,
    )

    sent_messages = llm.calls[0]["messages"]
    sent_text = " ".join(m["content"] for m in sent_messages if isinstance(m["content"], str))
    assert "123.456.789-00" not in sent_text
    assert "lead@example.com" not in sent_text
    assert "[CPF]" in sent_text
    assert "[EMAIL]" in sent_text

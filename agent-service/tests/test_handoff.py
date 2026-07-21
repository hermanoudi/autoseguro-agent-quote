from app.handoff import HandoffContext, build_handoff_context_package, evaluate_handoff
from app.quote_client import QuoteAttempt, QuoteOutcome


def _ctx(**overrides) -> HandoffContext:
    base = dict(
        lead_message="ola",
        lead_data={},
        quote_outcome=None,
        turns_without_progress=0,
        correction_attempts={},
    )
    base.update(overrides)
    return HandoffContext(**base)


class TestPedidoExplicitoDeHumano:
    def test_lead_pede_atendente(self):
        decision = evaluate_handoff(_ctx(lead_message="quero falar com um atendente"))
        assert decision.should_handoff is True
        assert decision.reason == "pedido_explicito_de_humano"

    def test_lead_pede_pessoa_de_verdade(self):
        decision = evaluate_handoff(_ctx(lead_message="da pra falar com uma pessoa de verdade?"))
        assert decision.should_handoff is True

    def test_mensagem_normal_nao_aciona(self):
        decision = evaluate_handoff(_ctx(lead_message="tenho 35 anos"))
        assert decision.should_handoff is False


class TestEsgotamentoDeTentativasDeCotacao:
    def test_falha_transitoria_esgotada_aciona_handoff(self):
        outcome = QuoteOutcome(success=False, error_class="transient", attempts=[])
        decision = evaluate_handoff(_ctx(quote_outcome=outcome))
        assert decision.should_handoff is True
        assert decision.reason == "esgotamento_tentativas_cotacao"

    def test_circuit_breaker_aberto_aciona_handoff(self):
        outcome = QuoteOutcome(success=False, error_class="circuit_open", attempts=[])
        decision = evaluate_handoff(_ctx(quote_outcome=outcome))
        assert decision.should_handoff is True
        assert decision.reason == "esgotamento_tentativas_cotacao"

    def test_recusa_de_negocio_pura_nao_aciona_handoff_automatico(self):
        outcome = QuoteOutcome(success=False, error_class="business_refusal", motivo="idade", attempts=[])
        decision = evaluate_handoff(_ctx(lead_message="ah entendi, obrigado", quote_outcome=outcome))
        assert decision.should_handoff is False

    def test_recusa_de_negocio_contestada_aciona_handoff(self):
        outcome = QuoteOutcome(success=False, error_class="business_refusal", motivo="idade", attempts=[])
        decision = evaluate_handoff(
            _ctx(lead_message="mas nao tem como fazer uma excecao?", quote_outcome=outcome)
        )
        assert decision.should_handoff is True
        assert decision.reason == "recusa_de_regra_contestada"


class TestEstagnacaoNaColetaDeDados:
    def test_abaixo_do_limiar_nao_aciona(self):
        decision = evaluate_handoff(_ctx(turns_without_progress=2))
        assert decision.should_handoff is False

    def test_atinge_o_limiar_aciona_handoff(self):
        decision = evaluate_handoff(_ctx(turns_without_progress=3))
        assert decision.should_handoff is True
        assert decision.reason == "estagnacao_na_coleta_de_dados"


class TestDadoInconsistenteAposCorrecoes:
    def test_uma_correcao_nao_aciona(self):
        decision = evaluate_handoff(_ctx(correction_attempts={"idade": 1}))
        assert decision.should_handoff is False

    def test_mais_de_duas_correcoes_aciona_handoff(self):
        decision = evaluate_handoff(_ctx(correction_attempts={"idade": 3}))
        assert decision.should_handoff is True
        assert decision.reason == "dado_inconsistente_apos_correcoes"


class TestPrioridadeEntreGatilhos:
    def test_pedido_de_humano_tem_prioridade_sobre_outros_gatilhos(self):
        outcome = QuoteOutcome(success=False, error_class="transient", attempts=[])
        decision = evaluate_handoff(
            _ctx(lead_message="quero falar com atendente", quote_outcome=outcome, turns_without_progress=5)
        )
        assert decision.reason == "pedido_explicito_de_humano"


class TestPacoteDeContexto:
    def test_contexto_inclui_dados_coletados_motivo_e_tentativas(self):
        attempts = [QuoteAttempt(quote_attempt_id="a1", attempt_no=1, status="transient", latency_ms=10.0)]
        package = build_handoff_context_package(
            conversation_id="conv_1",
            lead_data={"idade": 35, "veiculo_ano": 2020},
            reason="esgotamento_tentativas_cotacao",
            quote_attempts=attempts,
        )
        assert package["conversation_id"] == "conv_1"
        assert package["motivo"] == "esgotamento_tentativas_cotacao"
        assert package["dados_coletados"] == {"idade": 35, "veiculo_ano": 2020}
        assert package["tentativas_cotacao"][0]["quote_attempt_id"] == "a1"

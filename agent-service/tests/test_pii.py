import pytest

from app.pii import redact, redact_dict, pseudonymize


class TestRedactCPF:
    def test_cpf_with_punctuation(self):
        assert "123.456.789-00" not in redact("Meu CPF e 123.456.789-00, obrigado.")

    def test_cpf_bare_digits(self):
        assert "12345678900" not in redact("CPF: 12345678900")

    def test_cpf_placeholder_present(self):
        result = redact("CPF 123.456.789-00 aqui")
        assert "[CPF]" in result


class TestRedactPhone:
    def test_phone_with_parens_and_dash(self):
        assert "91234-5678" not in redact("Pode ligar no (11) 91234-5678 por favor")

    def test_phone_bare_digits(self):
        assert "11912345678" not in redact("meu numero e 11912345678")

    def test_phone_with_country_code(self):
        assert "91234-5678" not in redact("whatsapp: +55 11 91234-5678")

    def test_phone_placeholder_present(self):
        result = redact("me chama no (11) 91234-5678")
        assert "[TELEFONE]" in result


class TestRedactEmail:
    def test_standard_email(self):
        result = redact("contato: lead.teste@example.com.br")
        assert "lead.teste@example.com.br" not in result
        assert "[EMAIL]" in result


class TestRedactPlaca:
    def test_placa_formato_antigo(self):
        result = redact("a placa do carro e ABC-1234")
        assert "ABC-1234" not in result
        assert "[PLACA]" in result

    def test_placa_formato_mercosul(self):
        result = redact("placa ABC1D23 no documento")
        assert "ABC1D23" not in result
        assert "[PLACA]" in result


class TestRedactCEPParcial:
    def test_cep_com_hifen_preserva_prefixo(self):
        result = redact("moro no CEP 01310-100")
        assert "01310-100" not in result
        assert "01" in result

    def test_cep_sem_hifen_preserva_prefixo(self):
        from app.pii import redact_cep
        assert redact_cep("01310100") == "01******"

    def test_cep_com_hifen_formato_exato(self):
        from app.pii import redact_cep
        assert redact_cep("01310-100") == "01***-***"

    def test_cep_invalido_e_devolvido_sem_alteracao(self):
        from app.pii import redact_cep
        assert redact_cep("abc") == "abc"


class TestRedactDict:
    def test_redact_dict_applies_to_string_values(self):
        payload = {"mensagem": "meu email e lead@example.com", "idade": 35}
        result = redact_dict(payload)
        assert "lead@example.com" not in result["mensagem"]
        assert result["idade"] == 35

    def test_redact_dict_cep_field_uses_partial_redaction(self):
        payload = {"cep": "01310-100"}
        result = redact_dict(payload)
        assert result["cep"] == "01***-***"

    def test_redact_dict_nested_structures(self):
        payload = {"lead": {"telefone": "(11) 91234-5678", "nome": "Fulano"}}
        result = redact_dict(payload)
        assert "91234-5678" not in result["lead"]["telefone"]


class TestPseudonymize:
    def test_same_input_same_output(self):
        assert pseudonymize("12345678900", salt="abc") == pseudonymize("12345678900", salt="abc")

    def test_different_salt_different_output(self):
        assert pseudonymize("12345678900", salt="abc") != pseudonymize("12345678900", salt="xyz")

    def test_never_returns_original_value(self):
        original = "12345678900"
        assert pseudonymize(original, salt="abc") != original

    def test_output_is_stable_short_identifier(self):
        result = pseudonymize("12345678900", salt="abc")
        assert result.startswith("lead_")

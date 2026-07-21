from app.extraction import extract_lead_data


class TestExtractIdade:
    def test_idade_com_palavra_anos(self):
        assert extract_lead_data("tenho 35 anos")["idade"] == 35

    def test_idade_com_frase_de_idade(self):
        assert extract_lead_data("minha idade e 42 anos de idade")["idade"] == 42

    def test_sem_idade_nao_extrai(self):
        assert "idade" not in extract_lead_data("quero saber mais sobre o seguro")


class TestExtractVeiculoAno:
    def test_veiculo_texto_livre_com_ano(self):
        assert extract_lead_data("e um Sandero 2022")["veiculo_ano"] == 2022

    def test_veiculo_com_virgula_ano(self):
        assert extract_lead_data("Toyota Corolla, ano 2008")["veiculo_ano"] == 2008

    def test_nao_confunde_idade_com_ano_do_veiculo(self):
        data = extract_lead_data("tenho 35 anos e um Corolla 2020")
        assert data["idade"] == 35
        assert data["veiculo_ano"] == 2020

    def test_ano_fora_da_faixa_valida_nao_e_extraido(self):
        data = extract_lead_data("o carro e de 1920")
        assert "veiculo_ano" not in data


class TestExtractCEP:
    def test_cep_com_hifen(self):
        assert extract_lead_data("moro no CEP 01310-100")["cep"] == "01310-100"

    def test_cep_sem_hifen_e_normalizado(self):
        assert extract_lead_data("CEP 01310100")["cep"] == "01310-100"


class TestExtractPlano:
    def test_plano_essencial(self):
        assert extract_lead_data("quero o essencial")["plano_id"] == "essencial"

    def test_plano_completo_case_insensitive(self):
        assert extract_lead_data("prefiro o COMPLETO")["plano_id"] == "completo"

    def test_plano_premium(self):
        assert extract_lead_data("pode ser o premium")["plano_id"] == "premium"

    def test_sem_plano_nao_extrai(self):
        assert "plano_id" not in extract_lead_data("quero fazer um seguro")


class TestExtractDataInicio:
    def test_formato_iso(self):
        assert extract_lead_data("quero comecar em 2026-07-15")["data_inicio"] == "2026-07-15"

    def test_formato_br_dd_mm_yyyy(self):
        assert extract_lead_data("vigencia a partir de 15/07/2026")["data_inicio"] == "2026-07-15"


class TestExtractCombinado:
    def test_mensagem_completa_extrai_todos_os_campos(self):
        data = extract_lead_data(
            "tenho 35 anos, e um Corolla 2020, moro no CEP 01310-100, quero o completo, "
            "comecando em 15/07/2026"
        )
        assert data == {
            "idade": 35,
            "veiculo_ano": 2020,
            "cep": "01310-100",
            "plano_id": "completo",
            "data_inicio": "2026-07-15",
        }

    def test_mensagem_parcial_extrai_so_o_disponivel(self):
        data = extract_lead_data("tenho 28 anos")
        assert data == {"idade": 28}

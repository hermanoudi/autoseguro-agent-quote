import json

from app.store import ConversationStore


def test_get_or_create_e_o_mesmo_objeto_entre_chamadas(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    a = store.get_or_create("conv_1")
    b = store.get_or_create("conv_1")
    assert a is b


def test_add_message_acumula_na_mesma_conversa(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="ola")
    store.add_message("conv_1", role="agent", text="oi, tudo bem?")
    state = store.get_or_create("conv_1")
    assert len(state.messages) == 2
    assert state.messages[0].role == "lead"
    assert state.messages[1].role == "agent"


def test_add_message_gera_message_id_proprio(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    m1 = store.add_message("conv_1", role="lead", text="ola")
    m2 = store.add_message("conv_1", role="lead", text="tudo bem?")
    assert m1.message_id != m2.message_id


def test_update_lead_data_acumula_campos(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.update_lead_data("conv_1", idade=35)
    store.update_lead_data("conv_1", veiculo_ano=2022)
    state = store.get_or_create("conv_1")
    assert state.lead_data == {"idade": 35, "veiculo_ano": 2022}


def test_conversas_diferentes_sao_isoladas(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="msg 1")
    store.add_message("conv_2", role="lead", text="msg 2")
    assert len(store.get_or_create("conv_1").messages) == 1
    assert len(store.get_or_create("conv_2").messages) == 1


def test_jsonl_persistido_em_disco(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="ola")
    jsonl_path = tmp_path / "conv_1.jsonl"
    assert jsonl_path.exists()
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["type"] == "message"


def test_jsonl_persistido_com_pii_redigida(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.add_message("conv_1", role="lead", text="meu email e lead@example.com")
    jsonl_path = tmp_path / "conv_1.jsonl"
    content = jsonl_path.read_text(encoding="utf-8")
    assert "lead@example.com" not in content
    assert "[EMAIL]" in content


def test_update_lead_data_conta_correcao_quando_valor_muda(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.update_lead_data("conv_1", idade=35)
    store.update_lead_data("conv_1", idade=40)
    state = store.get_or_create("conv_1")
    assert state.lead_data["idade"] == 40
    assert state.field_correction_counts["idade"] == 1


def test_update_lead_data_nao_conta_correcao_quando_valor_repete(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.update_lead_data("conv_1", idade=35)
    store.update_lead_data("conv_1", idade=35)
    state = store.get_or_create("conv_1")
    assert state.field_correction_counts == {}


def test_mark_turn_progress_incrementa_sem_dado_novo_e_zera_com_dado_novo(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    assert store.mark_turn_progress("conv_1", had_new_data=False) == 1
    assert store.mark_turn_progress("conv_1", had_new_data=False) == 2
    assert store.mark_turn_progress("conv_1", had_new_data=True) == 0
    assert store.get_or_create("conv_1").turns_without_progress == 0


def test_set_status_atualiza_e_registra_evento(tmp_path):
    store = ConversationStore(storage_dir=tmp_path)
    store.set_status("conv_1", "handoff")
    assert store.get_or_create("conv_1").status == "handoff"
    jsonl_path = tmp_path / "conv_1.jsonl"
    event = json.loads(jsonl_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert event["type"] == "status_change"
    assert event["status"] == "handoff"

import json

from app.observability import configure_logging, get_logger, log_quote_attempt
from app.quote_client import QuoteAttempt


def _last_json_line(capsys) -> dict:
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


def test_log_estruturado_nao_contem_pii(capsys):
    configure_logging()
    logger = get_logger()

    logger.info("lead_message", conversation_id="conv_1", texto="contato: lead@example.com")

    event = _last_json_line(capsys)
    assert "lead@example.com" not in json.dumps(event)
    assert "[EMAIL]" in event["texto"]


def test_log_quote_attempt_inclui_campos_de_rastreabilidade(capsys):
    configure_logging()
    logger = get_logger()
    attempt = QuoteAttempt(
        quote_attempt_id="attempt-1", attempt_no=1, status="success", latency_ms=123.456, http_status=200
    )

    log_quote_attempt(logger, conversation_id="conv_1", attempt=attempt)

    event = _last_json_line(capsys)
    assert event["conversation_id"] == "conv_1"
    assert event["quote_attempt_id"] == "attempt-1"
    assert event["attempt_no"] == 1
    assert event["status"] == "success"
    assert event["latency_ms"] == 123.46
    assert event["http_status"] == 200


def test_log_quote_attempt_com_cep_nos_dados_extras_preserva_prefixo(capsys):
    configure_logging()
    logger = get_logger()
    attempt = QuoteAttempt(quote_attempt_id="a1", attempt_no=1, status="success", latency_ms=1.0)

    log_quote_attempt(logger, conversation_id="conv_1", attempt=attempt, cep="01310-100")

    event = _last_json_line(capsys)
    assert event["cep"] == "01***-***"

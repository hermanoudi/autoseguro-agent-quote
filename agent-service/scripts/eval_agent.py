"""Roda o eval set contra o agent-service real (HTTP), exercitando o loop
conversacional completo — extração determinística + LLM + tool calling — em vez de só
a camada de regex (isso é `eval_extraction.py`, que não depende de rede nem de chave).

Para cada caso, abre uma conversa nova e reenvia só as mensagens do `lead` do
transcript original (as respostas do vendedor humano no dataset não fazem sentido
aqui; é o nosso agente que responde). Depois de tudo enviado, reconstrói o
`lead_data` final lendo o JSONL de auditoria que o `ConversationStore` já grava
(evento `lead_data_update`), sem precisar de nenhum endpoint novo de introspecção.

Requer o agent-service rodando (uv run uvicorn ou docker compose) com um
OPENAI_API_KEY válido, e o quote-service acessível.

Uso: uv run python scripts/eval_agent.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import httpx

AGENT_URL = "http://localhost:8001"
EVAL_SET_PATH = Path(__file__).resolve().parent.parent / "eval" / "eval_set.jsonl"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"

_PRECO_RE = re.compile(r"R\$\s*\d")


def _final_lead_data(conversation_id: str) -> dict:
    path = DATA_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        return {}
    lead_data: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "lead_data_update":
            lead_data.update(event["fields"])
    return lead_data


def run_case(client: httpx.Client, case: dict) -> dict:
    conversation_id = f"eval_{case['conversation_id']}"
    lead_turns = [m["text"] for m in case["transcript"] if m["role"] == "lead"]

    last_reply = ""
    last_status = "active"
    got_price = False
    for text in lead_turns:
        resp = client.post(
            f"{AGENT_URL}/message", json={"conversation_id": conversation_id, "text": text}
        )
        resp.raise_for_status()
        body = resp.json()
        last_reply = body["reply"]
        last_status = body["status"]
        if _PRECO_RE.search(last_reply):
            got_price = True
        if last_status == "handoff":
            break

    lead_data = _final_lead_data(conversation_id)
    idade_ok = case["expected_idade"] is None or lead_data.get("idade") == case["expected_idade"]
    ano_ok = (
        case["expected_veiculo_ano"] is None
        or lead_data.get("veiculo_ano") == case["expected_veiculo_ano"]
    )

    return {
        "conversation_id": case["conversation_id"],
        "status": last_status,
        "got_price": got_price,
        "idade_ok": idade_ok,
        "ano_ok": ano_ok,
        "expected_idade": case["expected_idade"],
        "extracted_idade": lead_data.get("idade"),
        "expected_veiculo_ano": case["expected_veiculo_ano"],
        "extracted_veiculo_ano": lead_data.get("veiculo_ano"),
        "last_reply": last_reply,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cases = [json.loads(line) for line in EVAL_SET_PATH.read_text(encoding="utf-8").splitlines()]
    if args.limit:
        cases = cases[: args.limit]

    results = []
    with httpx.Client(timeout=60.0) as client:
        for i, case in enumerate(cases, 1):
            result = run_case(client, case)
            results.append(result)
            marker = "OK" if result["idade_ok"] and result["ano_ok"] else "MISMATCH"
            print(
                f"[{i}/{len(cases)}] {result['conversation_id']}: status={result['status']} "
                f"price={result['got_price']} idade={result['extracted_idade']}"
                f"(esperado {result['expected_idade']}) "
                f"ano={result['extracted_veiculo_ano']}(esperado {result['expected_veiculo_ano']}) "
                f"[{marker}]"
            )

    total = len(results)
    idade_acertos = sum(1 for r in results if r["idade_ok"])
    ano_acertos = sum(1 for r in results if r["ano_ok"])
    quotes = sum(1 for r in results if r["got_price"])
    handoffs = sum(1 for r in results if r["status"] == "handoff")

    print("\n--- resumo ---")
    print(f"casos avaliados: {total}")
    print(f"idade correta:        {idade_acertos}/{total} ({idade_acertos/total:.0%})")
    print(f"veiculo_ano correto:  {ano_acertos}/{total} ({ano_acertos/total:.0%})")
    print(f"cotação com preço:    {quotes}/{total} ({quotes/total:.0%})")
    print(f"terminaram em handoff: {handoffs}/{total} ({handoffs/total:.0%})")

    mismatches = [r for r in results if not (r["idade_ok"] and r["ano_ok"])]
    if mismatches:
        print(f"\n{len(mismatches)} caso(s) com extração divergente:")
        for r in mismatches:
            print(f"  - {r['conversation_id']}: {r}")


if __name__ == "__main__":
    main()

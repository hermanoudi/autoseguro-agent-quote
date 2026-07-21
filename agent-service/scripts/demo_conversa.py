"""Roda uma conversa completa contra o agent-service via HTTP e grava o log de
execução exigido pela entrega.

Requer o agent-service rodando (docker compose up, ou uv run uvicorn) com um
ANTHROPIC_API_KEY válido carregado via `.env`. Para o cenário de falha total, suba o
`quote-service` com `QUOTE_FAILURE_RATE=1.0` antes de rodar este script (ver
CLAUDE.md: `docker-compose.yml` fixa as taxas, então rode a API direto com `uv run
uvicorn` para variar isso).

Uso:
  uv run python scripts/demo_conversa.py --scenario sucesso
  uv run python scripts/demo_conversa.py --scenario falha_total
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

AGENT_URL = "http://localhost:8001"

ROTEIRO = [
    "Oi, queria fazer um seguro pro meu carro",
    "Tenho 35 anos e o carro e um Corolla 2020",
    "Quero o plano completo",
    "Meu cep e 01310-100, pode comecar dia 15/07/2026",
]

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def run_scenario(name: str) -> Path:
    conversation_id = f"demo_{name}_{uuid.uuid4().hex[:8]}"
    log_path = LOG_DIR / f"demo_{name}.jsonl"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    events = []
    with httpx.Client(timeout=30.0) as client:
        for text in ROTEIRO:
            resp = client.post(
                f"{AGENT_URL}/message", json={"conversation_id": conversation_id, "text": text}
            )
            resp.raise_for_status()
            body = resp.json()
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
                "lead": text,
                "agente": body["reply"],
                "status": body["status"],
            }
            events.append(event)
            print(f"LEAD:   {text}")
            print(f"AGENTE: {body['reply']}")
            print(f"status: {body['status']}\n")
            if body["status"] == "handoff":
                break

    log_path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8"
    )
    print(f"log salvo em {log_path}")
    return log_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["sucesso", "falha_total"], required=True)
    args = parser.parse_args()
    run_scenario(args.scenario)


if __name__ == "__main__":
    main()

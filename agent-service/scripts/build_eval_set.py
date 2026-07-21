"""Constrói um eval set a partir do dataset de conversas do desafio.

Usa `conversation_outcome`, `lead_idade_informada` e `veiculo_texto` (colunas
estruturadas já presentes no dataset) como verdade de referência para idade e ano do
veículo — não exige LLM. O transcript persistido é redigido pelo módulo de PII antes
de tocar o disco (nenhuma conversa bruta é commitada).

Uso: uv run python scripts/build_eval_set.py [--n 25] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import extract_lead_data
from app.pii import redact

DATASET_PATH = Path(__file__).resolve().parents[2] / "dataset" / "conversations.parquet"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "eval" / "eval_set.jsonl"


def _expected_veiculo_ano(veiculo_texto: str | None) -> int | None:
    if not veiculo_texto:
        return None
    return extract_lead_data(veiculo_texto).get("veiculo_ano")


def build(n: int, seed: int) -> list[dict]:
    df = pd.read_parquet(DATASET_PATH)
    df = df.sort_values(["conversation_id", "message_index"])

    conv_ids = df["conversation_id"].drop_duplicates()
    sample_ids = conv_ids.sample(n=min(n, len(conv_ids)), random_state=seed).tolist()

    cases = []
    for conv_id in sample_ids:
        conv = df[df["conversation_id"] == conv_id]
        first = conv.iloc[0]
        transcript = [
            {
                "role": "lead" if row.sender_role == "lead" else "agent",
                "text": redact(row.message_body) if row.message_type == "text" else f"[{row.message_type}]",
            }
            for row in conv.itertuples()
        ]
        cases.append(
            {
                "conversation_id": conv_id,
                "transcript": transcript,
                "expected_idade": int(first.lead_idade_informada)
                if pd.notna(first.lead_idade_informada)
                else None,
                "expected_veiculo_ano": _expected_veiculo_ano(first.veiculo_texto),
                "conversation_outcome": first.conversation_outcome,
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cases = build(args.n, args.seed)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"{len(cases)} casos escritos em {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

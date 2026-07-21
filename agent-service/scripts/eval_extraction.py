"""Mede a acurácia da extração determinística (`app.extraction`) contra o eval set.

Não depende de ANTHROPIC_API_KEY: exercita só a camada regex/heurística que roda
antes do LLM. É a parte de "rodar o agente contra o eval set" que dá para validar sem
chave de API — a validação do loop conversacional completo (LLM + tool calling) precisa
de uma chave real, ver README.

Uso: uv run python scripts/eval_extraction.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import extract_lead_data

EVAL_SET_PATH = Path(__file__).resolve().parent.parent / "eval" / "eval_set.jsonl"


def main() -> None:
    cases = [json.loads(line) for line in EVAL_SET_PATH.read_text(encoding="utf-8").splitlines()]

    idade_total = idade_acertos = 0
    ano_total = ano_acertos = 0

    for case in cases:
        lead_text = " ".join(m["text"] for m in case["transcript"] if m["role"] == "lead")
        extracted = extract_lead_data(lead_text)

        if case["expected_idade"] is not None:
            idade_total += 1
            if extracted.get("idade") == case["expected_idade"]:
                idade_acertos += 1

        if case["expected_veiculo_ano"] is not None:
            ano_total += 1
            if extracted.get("veiculo_ano") == case["expected_veiculo_ano"]:
                ano_acertos += 1

    print(f"casos avaliados: {len(cases)}")
    if idade_total:
        print(f"idade:        {idade_acertos}/{idade_total} ({idade_acertos / idade_total:.0%})")
    if ano_total:
        print(f"veiculo_ano:  {ano_acertos}/{ano_total} ({ano_acertos / ano_total:.0%})")


if __name__ == "__main__":
    main()

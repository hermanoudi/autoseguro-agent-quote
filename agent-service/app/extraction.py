"""Extração determinística de dados estruturados a partir de texto livre.

Camada barata e testável que roda antes do LLM: reduz a dependência do modelo para
campos com padrão reconhecível (idade, ano do veículo, CEP, plano, data de início).
O que não for reconhecido aqui fica para a conversa (o agente pergunta).
"""
from __future__ import annotations

import re

_IDADE_RE = re.compile(r"\b(\d{1,3})\s*anos\b", re.IGNORECASE)
_ANO_VEICULO_RE = re.compile(r"\b(19[5-9]\d|20\d{2}|2100)\b")
_CEP_RE = re.compile(r"\b(\d{5})-?(\d{3})\b")
_PLANO_RE = re.compile(r"\b(essencial|completo|premium)\b", re.IGNORECASE)
_DATA_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATA_BR_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

_PLANOS_VALIDOS = {"essencial", "completo", "premium"}


def _extract_idade(text: str) -> int | None:
    match = _IDADE_RE.search(text)
    return int(match.group(1)) if match else None


def _extract_veiculo_ano(text: str, idade_span: tuple[int, int] | None) -> int | None:
    for match in _ANO_VEICULO_RE.finditer(text):
        if idade_span and idade_span[0] <= match.start() < idade_span[1]:
            continue
        return int(match.group(1))
    return None


def _extract_cep(text: str) -> str | None:
    match = _CEP_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _extract_plano(text: str) -> str | None:
    match = _PLANO_RE.search(text)
    if not match:
        return None
    plano = match.group(1).lower()
    return plano if plano in _PLANOS_VALIDOS else None


def _extract_data_inicio(text: str) -> str | None:
    iso_match = _DATA_ISO_RE.search(text)
    if iso_match:
        return iso_match.group(0)
    br_match = _DATA_BR_RE.search(text)
    if br_match:
        dia, mes, ano = br_match.groups()
        return f"{ano}-{mes}-{dia}"
    return None


def extract_lead_data(text: str) -> dict:
    """Retorna apenas os campos reconhecidos; ausentes não entram no dict."""
    data: dict = {}

    idade_match = _IDADE_RE.search(text)
    if idade_match:
        data["idade"] = int(idade_match.group(1))

    veiculo_ano = _extract_veiculo_ano(text, idade_match.span() if idade_match else None)
    if veiculo_ano is not None:
        data["veiculo_ano"] = veiculo_ano

    cep = _extract_cep(text)
    if cep is not None:
        data["cep"] = cep

    plano_id = _extract_plano(text)
    if plano_id is not None:
        data["plano_id"] = plano_id

    data_inicio = _extract_data_inicio(text)
    if data_inicio is not None:
        data["data_inicio"] = data_inicio

    return data

"""Redação de dados sensíveis (PII).

Módulo único, reusado em log estruturado, transcrição de conversa e no pipeline de
preparação do dataset. CEP recebe redação parcial (preserva os 2 primeiros dígitos,
necessários para o cálculo do agravo de região); os demais dados sensíveis são
substituídos por placeholder.
"""
from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PLACA_RE = re.compile(r"\b[A-Za-z]{3}-?\d[A-Za-z0-9]\d{2}\b")
CEP_COM_HIFEN_RE = re.compile(r"\b\d{5}-\d{3}\b")
PHONE_RE = re.compile(
    r"(?:\+?55[\s.-]?)?"       # codigo do pais, opcional
    r"\(?\d{2}\)?[\s.-]?"      # DDD, parenteses opcionais
    r"9?\d{4}[\s.-]?\d{4}\b"   # numero local, marcador de celular opcional
)
CPF_FORMATADO_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_BARE_RE = re.compile(r"\b\d{11}\b")


def redact_cep(cep: str) -> str:
    """Preserva o prefixo de 2 dígitos (usado no agravo de região) e redige o resto."""
    digits = re.sub(r"\D", "", cep)
    if len(digits) != 8:
        return cep
    prefix = digits[:2]
    if "-" in cep:
        return f"{prefix}***-***"
    return prefix + "*" * 6


def _redact_cep_match(match: re.Match) -> str:
    return redact_cep(match.group(0))


def redact(text: str) -> str:
    """Redige CPF, telefone, e-mail, placa e CEP (parcial) em texto livre."""
    if not text:
        return text
    result = EMAIL_RE.sub("[EMAIL]", text)
    result = PLACA_RE.sub("[PLACA]", result)
    result = CEP_COM_HIFEN_RE.sub(_redact_cep_match, result)
    result = PHONE_RE.sub("[TELEFONE]", result)
    result = CPF_FORMATADO_RE.sub("[CPF]", result)
    result = CPF_BARE_RE.sub("[CPF]", result)
    return result


def redact_dict(obj):
    """Aplica a redação recursivamente. O campo `cep` recebe redação parcial."""
    if isinstance(obj, dict):
        redacted = {}
        for key, value in obj.items():
            if isinstance(value, str) and key.lower() == "cep":
                redacted[key] = redact_cep(value)
            elif isinstance(value, (dict, list)):
                redacted[key] = redact_dict(value)
            elif isinstance(value, str):
                redacted[key] = redact(value)
            else:
                redacted[key] = value
        return redacted
    if isinstance(obj, list):
        return [
            redact_dict(item) if isinstance(item, (dict, list))
            else redact(item) if isinstance(item, str)
            else item
            for item in obj
        ]
    return obj


def pseudonymize(value: str, salt: str) -> str:
    """Identificador estável derivado por hash, nunca o valor original."""
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:12]
    return f"lead_{digest}"


def structlog_pii_processor(logger, method_name, event_dict):
    """Processor do structlog: redige PII em todos os valores do evento de log.

    Ligado em `app.observability.configure_logging` para que a redação aconteça por
    construção em toda mensagem de log, não por disciplina de quem escreve a linha.
    """
    return redact_dict(event_dict)

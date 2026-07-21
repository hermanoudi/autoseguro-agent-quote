"""Wrapper fino sobre o SDK Anthropic.

Isola a chamada de rede atrás de um formato próprio e simples (`LLMResponse`,
`TextBlock`, `ToolUseBlock`) para que `app.agent` nunca dependa diretamente do
shape de resposta do SDK, e para que os testes usem um cliente fake sem precisar de
`ANTHROPIC_API_KEY` nem de chamada de rede real.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class LLMResponse:
    content: list  # list[TextBlock | ToolUseBlock]

    def first_text(self) -> str | None:
        for block in self.content:
            if isinstance(block, TextBlock):
                return block.text
        return None

    def tool_use(self) -> ToolUseBlock | None:
        for block in self.content:
            if isinstance(block, ToolUseBlock):
                return block
        return None


class LLMClient(Protocol):
    async def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class AnthropicLLMClient:
    """Cliente real, usado em produção. Requer ANTHROPIC_API_KEY no ambiente (.env)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    async def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=tools,
        )
        blocks = []
        for block in response.content:
            if block.type == "text":
                blocks.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                blocks.append(ToolUseBlock(id=block.id, name=block.name, input=dict(block.input)))
        return LLMResponse(content=blocks)

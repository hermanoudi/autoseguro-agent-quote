"""Wrapper fino sobre o SDK OpenAI.

Isola a chamada de rede atrás de um formato próprio e simples (`LLMResponse`,
`TextBlock`, `ToolUseBlock`) para que `app.agent` nunca dependa diretamente do
shape de resposta do SDK, e para que os testes usem um cliente fake sem precisar de
`OPENAI_API_KEY` nem de chamada de rede real.
"""
from __future__ import annotations

import json
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


class OpenAILLMClient:
    """Cliente real, usado em produção. Requer OPENAI_API_KEY no ambiente (.env).

    `system` chega como parâmetro separado (mesmo formato do Protocol usado pelo
    resto do código) e é traduzido aqui para a primeira mensagem `role: system` que a
    Chat Completions API espera — `app.agent` não precisa saber disso.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "system", "content": system}, *messages],
            tools=tools,
        )
        message = response.choices[0].message
        blocks = []
        if message.content:
            blocks.append(TextBlock(text=message.content))
        for tool_call in message.tool_calls or []:
            blocks.append(
                ToolUseBlock(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=json.loads(tool_call.function.arguments),
                )
            )
        return LLMResponse(content=blocks)

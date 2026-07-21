"""Estado da conversa: memória (fonte de verdade em runtime) + JSONL append-only por
`conversation_id` (trilha de auditoria, com PII redigida antes de gravar em disco).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.pii import redact_dict


@dataclass
class Message:
    message_id: str
    role: str  # "lead" | "agent"
    text: str
    timestamp: str


@dataclass
class ConversationState:
    conversation_id: str
    messages: list[Message] = field(default_factory=list)
    lead_data: dict = field(default_factory=dict)
    status: str = "active"  # "active" | "handoff" | "closed"
    turns_without_progress: int = 0
    field_correction_counts: dict = field(default_factory=dict)


class ConversationStore:
    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._conversations: dict[str, ConversationState] = {}

    def get_or_create(self, conversation_id: str) -> ConversationState:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = ConversationState(conversation_id=conversation_id)
        return self._conversations[conversation_id]

    def add_message(self, conversation_id: str, role: str, text: str) -> Message:
        state = self.get_or_create(conversation_id)
        message = Message(
            message_id=str(uuid.uuid4()),
            role=role,
            text=text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        state.messages.append(message)
        self._append_jsonl(conversation_id, {"type": "message", **asdict(message)})
        return message

    def update_lead_data(self, conversation_id: str, **fields) -> None:
        state = self.get_or_create(conversation_id)
        clean_fields = {k: v for k, v in fields.items() if v is not None}
        for key, value in clean_fields.items():
            existing = state.lead_data.get(key)
            if existing is not None and existing != value:
                state.field_correction_counts[key] = state.field_correction_counts.get(key, 0) + 1
        state.lead_data.update(clean_fields)
        self._append_jsonl(conversation_id, {"type": "lead_data_update", "fields": clean_fields})

    def mark_turn_progress(self, conversation_id: str, had_new_data: bool) -> int:
        """Zera a contagem quando o turno trouxe dado novo; incrementa quando não trouxe."""
        state = self.get_or_create(conversation_id)
        state.turns_without_progress = 0 if had_new_data else state.turns_without_progress + 1
        return state.turns_without_progress

    def set_status(self, conversation_id: str, status: str) -> None:
        state = self.get_or_create(conversation_id)
        state.status = status
        self._append_jsonl(conversation_id, {"type": "status_change", "status": status})

    def _append_jsonl(self, conversation_id: str, event: dict) -> None:
        path = self._storage_dir / f"{conversation_id}.jsonl"
        redacted_event = redact_dict(event)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(redacted_event, ensure_ascii=False) + "\n")

"""Validated model output DTOs; never execution authority."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    origin: Literal["user_statement", "assistant_inference", "tool_observation"]
    refs: list[str] = Field(min_length=1, max_length=16)
    status: Literal["active", "superseded", "uncertain"] = "active"


class ConversationDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: list[MemoryEntry] = Field(default_factory=list, max_length=16)
    constraints: list[MemoryEntry] = Field(default_factory=list, max_length=48)
    decisions: list[MemoryEntry] = Field(default_factory=list, max_length=48)
    pending_questions: list[MemoryEntry] = Field(default_factory=list, max_length=24)
    next_actions: list[MemoryEntry] = Field(default_factory=list, max_length=24)
    evidence: list[MemoryEntry] = Field(default_factory=list, max_length=32)
    uncertainties: list[MemoryEntry] = Field(default_factory=list, max_length=24)

    def entries(self):
        return [entry for name in type(self).model_fields for entry in getattr(self, name)]

    def render(self):
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))

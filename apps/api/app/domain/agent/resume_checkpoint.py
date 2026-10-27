"""A fixed resume precondition, not permission to confirm a tool or run a goal."""
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping, Optional
from .active_runtime import validate_active_clock


RESUME_CHECKPOINT_SCHEMA = "nasus.agent-resume-checkpoint.v1"
ACTIVE_CHECKPOINT_SCHEMA = "nasus.agent-resume-checkpoint.v2"
ACTIVE_CLOCK_FIELDS = frozenset({"active_runtime_ms", "active_started_at"})
GOAL_CHECKPOINT_FIELDS = (
    "id", "conversation_id", "project_id", "us_id", "goal_template", "goal_description",
    "target_refs", "query_keys", "planner_kind", "planning_summary", "title", "status",
    "summary", "steps", "autonomy_level", "max_steps", "max_model_calls",
    "max_thinking_tokens", "max_runtime_seconds", "max_no_progress_observations",
    "steps_completed", "model_calls_used", "thinking_input_tokens_used",
    "thinking_output_tokens_used", "thinking_tokens_used", "no_progress_observations",
    "started_at", "last_progress_at", "last_progress_fingerprint",
    "budget_exhausted_reason", "pause_reason", "workflow_id",
)
GOAL_STATUSES = frozenset({"draft", "pending", "running", "paused", "blocked", "completed", "failed", "cancelled"})


class InvalidAgentResumeCheckpoint(ValueError):
    pass


class AgentResumeCheckpointChanged(ValueError):
    def __init__(self):
        super().__init__("The AgentGoal checkpoint changed; reload before resuming.")


def _identity(value, *, nullable=False):
    if nullable and value is None:
        return value
    if type(value) is not str or not value or len(value) > 128:
        raise InvalidAgentResumeCheckpoint("Invalid resume checkpoint scope.")
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise InvalidAgentResumeCheckpoint("Resume checkpoint must be a mapping.")
    fields = set(payload)
    schema = RESUME_CHECKPOINT_SCHEMA
    if fields == set(GOAL_CHECKPOINT_FIELDS) | ACTIVE_CLOCK_FIELDS:
        if payload["active_runtime_ms"] is None:
            raise InvalidAgentResumeCheckpoint("A v2 checkpoint requires active runtime accounting.")
        try:
            validate_active_clock(payload["active_runtime_ms"], payload["active_started_at"])
        except ValueError as exc:
            raise InvalidAgentResumeCheckpoint("Invalid resume checkpoint runtime clock.") from exc
        schema = ACTIVE_CHECKPOINT_SCHEMA
    elif fields != set(GOAL_CHECKPOINT_FIELDS):
        raise InvalidAgentResumeCheckpoint("Resume checkpoint schema differs from v1/v2.")
    if type(payload["status"]) is not str or payload["status"] not in GOAL_STATUSES or type(payload["steps"]) is not list or len(payload["steps"]) > 512:
        raise InvalidAgentResumeCheckpoint("Invalid resume checkpoint state.")
    try:
        encoded = json.dumps({"schema": schema, "goal": dict(payload)},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidAgentResumeCheckpoint("Resume checkpoint must contain bounded JSON.") from exc
    if len(encoded) > 512 * 1024:
        raise InvalidAgentResumeCheckpoint("Resume checkpoint exceeds 512 KiB.")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AgentResumeCheckpoint:
    goal_id: str
    conversation_id: str
    project_id: Optional[str]
    workflow_id: Optional[str]
    digest: str

    def __post_init__(self):
        _identity(self.goal_id)
        _identity(self.conversation_id)
        _identity(self.project_id, nullable=True)
        _identity(self.workflow_id, nullable=True)
        if type(self.digest) is not str or not self.digest.startswith("sha256:") or len(self.digest) != 71:
            raise InvalidAgentResumeCheckpoint("Invalid resume checkpoint digest.")
        if any(char not in "0123456789abcdef" for char in self.digest[7:]):
            raise InvalidAgentResumeCheckpoint("Invalid resume checkpoint digest.")

    @classmethod
    def capture(cls, payload: Mapping[str, Any]):
        digest = _digest(payload)
        if payload["status"] not in {"paused", "blocked"}:
            raise InvalidAgentResumeCheckpoint("Resume requires a paused or blocked AgentGoal.")
        if payload.get("active_started_at") is not None:
            raise InvalidAgentResumeCheckpoint("A paused checkpoint must settle its active interval.")
        return cls(payload["id"], payload["conversation_id"], payload["project_id"], payload["workflow_id"], digest)

    @classmethod
    def from_payload(cls, payload):
        if type(payload) is not dict or set(payload) != {"goal_id", "conversation_id", "project_id", "workflow_id", "digest"}:
            raise InvalidAgentResumeCheckpoint("Invalid queued resume checkpoint schema.")
        return cls(**payload)

    def require_scope(self, payload: Mapping[str, Any]):
        if (payload.get("id"), payload.get("conversation_id"), payload.get("project_id"), payload.get("workflow_id")) != (
                self.goal_id, self.conversation_id, self.project_id, self.workflow_id):
            raise AgentResumeCheckpointChanged()

    def require_matches(self, payload: Mapping[str, Any]):
        self.require_scope(payload)
        if _digest(payload) != self.digest:
            raise AgentResumeCheckpointChanged()

    def require_transition(self, payload: Mapping[str, Any]):
        self.require_scope(payload)
        if payload.get("status") != "running" or payload.get("pause_reason") is not None:
            raise InvalidAgentResumeCheckpoint("A resume commit must consume the paused checkpoint.")
        if "active_runtime_ms" in payload and payload.get("active_started_at") is None:
            raise InvalidAgentResumeCheckpoint("A tracked resume must start an active interval.")

    def payload(self) -> dict:
        return asdict(self)

    def consumption(self, transition: Mapping[str, Any]) -> dict:
        self.require_transition(transition)
        value = {"schema": "nasus.agent-resume-consumption.v1", "checkpoint": self.payload(),
            "transition_digest": _digest(transition)}
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return {**value, "receipt_hash": "sha256:" + hashlib.sha256(encoded).hexdigest()}

    def require_consumption(self, transition_digest: str, receipt_hash: str):
        value = {"schema": "nasus.agent-resume-consumption.v1", "checkpoint": self.payload(),
            "transition_digest": transition_digest}
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if receipt_hash != "sha256:" + hashlib.sha256(encoded).hexdigest():
            raise InvalidAgentResumeCheckpoint("Resume consumption failed integrity verification.")

"""Creation conflicts carry identity, never a second execution request."""

from dataclasses import dataclass
import hashlib
import json
import re

from .plan_policy import AgentPlanPolicyViolation

ACTIVE_AGENT_GOAL_STATUSES = frozenset({"pending", "running", "paused", "blocked"})


class ActiveAgentGoalExists(Exception):
    def __init__(self, goal_id: str):
        self.goal_id = goal_id
        super().__init__("An active goal already controls this conversation.")


START_RECEIPT_SCHEMA = "nasus.agent-goal-start.v1"


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AgentGoalStartIdentity:
    workflow_id: str
    request_digest: str

    def __post_init__(self):
        if (type(self.workflow_id) is not str or not 1 <= len(self.workflow_id) <= 256
                or any(ord(value) < 32 for value in self.workflow_id)
                or type(self.request_digest) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", self.request_digest) is None):
            raise AgentPlanPolicyViolation("agent_start_identity_invalid", "Invalid durable goal start identity.")

    @classmethod
    def capture(cls, workflow_id, request):
        return cls(workflow_id, _digest({"schema": START_RECEIPT_SCHEMA, "request": request}))

    def receipt(self, goal_id, conversation_id, project_id):
        payload = {"schema_version": START_RECEIPT_SCHEMA, "workflow_id": self.workflow_id,
            "request_digest": self.request_digest, "goal_id": goal_id,
            "conversation_id": conversation_id, "project_id": project_id}
        return {**payload, "receipt_hash": _digest(payload)}

    def require_receipt(self, receipt, conversation_id, project_id):
        if receipt != self.receipt(receipt["goal_id"], conversation_id, project_id):
            raise AgentPlanPolicyViolation("agent_start_scope_changed", "The durable start no longer matches its original request or controller.")


class AgentGoalStartReplayed(Exception):
    def __init__(self, goal_id):
        self.goal_id = goal_id
        super().__init__("The durable start already created its original goal.")


class AgentGoalStartRecoveryRequired(Exception):
    def __init__(self, goal_id):
        self.goal_id = goal_id
        super().__init__("The original goal requires execution recovery; its start cannot release a confirmation.")

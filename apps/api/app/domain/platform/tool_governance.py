from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol


GateStatus = Literal["allow", "waiting_confirmation", "waiting_approval"]


class ToolGateSubject(Protocol):
    label: str
    confirmation_mode: str
    risk_level: str


class InvocationGateSubject(Protocol):
    input_payload: dict


ApprovalVerifier = Callable[[InvocationGateSubject], tuple[bool, str]]


@dataclass(frozen=True)
class ToolGateDecision:
    status: GateStatus
    summary: str
    confirmation_mode: str = "none"
    risk_level: str = "low"

    @property
    def is_blocking(self) -> bool:
        return self.status != "allow"


class ToolGovernance:
    """Pure governance-gate policy for tool execution.

    The policy decides whether a tool can proceed, needs user confirmation, or
    needs approval. It accepts protocol-shaped inputs so application DTOs and
    future persistence records can use the same rule table without leaking
    concrete models into the domain layer.
    """

    def __init__(self, approval_verifier: ApprovalVerifier | None = None) -> None:
        self.approval_verifier = approval_verifier

    @staticmethod
    def is_confirmation_message(content: str) -> bool:
        normalized = content.strip().lower()
        if not normalized:
            return False
        confirmation_needles = {
            "confirm",
            "confirmed",
            "approve",
            "approved",
            "continue",
            "proceed",
            "yes",
            "ok",
            "okay",
            "go ahead",
            "确认",
            "同意",
            "继续",
            "执行",
            "可以",
            "批准",
        }
        return any(needle in normalized for needle in confirmation_needles)

    def evaluate(self, tool: ToolGateSubject | None, invocation: InvocationGateSubject) -> ToolGateDecision:
        if tool is None:
            return ToolGateDecision(status="allow", summary="No tool definition was registered.")

        if tool.confirmation_mode == "user_confirm" and invocation.input_payload.get("confirmed_by_user") is not True:
            return ToolGateDecision(
                status="waiting_confirmation",
                summary=f"{tool.label} requires user confirmation before execution.",
                confirmation_mode=tool.confirmation_mode,
                risk_level=tool.risk_level,
            )

        if tool.confirmation_mode == "approval_required":
            if invocation.input_payload.get("approval_id") is None:
                return ToolGateDecision(
                    status="waiting_approval",
                    summary=f"{tool.label} requires approval before execution.",
                    confirmation_mode=tool.confirmation_mode,
                    risk_level=tool.risk_level,
                )
            if self.approval_verifier is not None:
                allowed, summary = self.approval_verifier(invocation)
                if not allowed:
                    return ToolGateDecision(
                        status="waiting_approval",
                        summary=summary,
                        confirmation_mode=tool.confirmation_mode,
                        risk_level=tool.risk_level,
                    )

        return ToolGateDecision(
            status="allow",
            summary=f"{tool.label} is allowed by policy.",
            confirmation_mode=tool.confirmation_mode,
            risk_level=tool.risk_level,
        )

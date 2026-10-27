from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityStepGuidance:
    running_summary: str
    assistant_followup: str


DEFAULT_QUALITY_STEP_GUIDANCE = QualityStepGuidance(
    running_summary="Running quality-loop tool",
    assistant_followup="I will continue with the next quality-loop step.",
)


QUALITY_STEP_GUIDANCE: dict[str, QualityStepGuidance] = {
    "scenarios": QualityStepGuidance(
        running_summary="Generating scenario pack",
        assistant_followup="The generated scenarios remain drafts. Independent review is required before they can be treated as approved.",
    ),
    "cases": QualityStepGuidance(
        running_summary="Generating structured test cases",
        assistant_followup="The generated cases remain drafts. Next I can prepare an automation blueprint for review.",
    ),
    "verification_plan": QualityStepGuidance(
        running_summary="Generating verification plan",
        assistant_followup="The generated verification plan remains a draft. Independent review is required before it can be treated as approved.",
    ),
    "automation": QualityStepGuidance(
        running_summary="Generating a reviewable automation asset",
        assistant_followup=(
            "The blueprint is a draft. Independent review, a fixed target and separate execution authorization remain required."
        ),
    ),
    "scope": QualityStepGuidance(
        running_summary="Generating test scope from system image context",
        assistant_followup="Next I can draft scenarios; coverage has not yet been measured.",
    ),
    "change_document": QualityStepGuidance(
        running_summary="Generating traceable quality change document",
        assistant_followup="The change record is a draft. Release assessment must verify independent quality and execution evidence.",
    ),
    "release": QualityStepGuidance(
        running_summary="Assessing release readiness",
        assistant_followup="The quality loop is ready for human release review or governance follow-up.",
    ),
}


def quality_step_guidance(step: str) -> QualityStepGuidance:
    return QUALITY_STEP_GUIDANCE.get(step, DEFAULT_QUALITY_STEP_GUIDANCE)


def quality_step_running_summary(step: str) -> str:
    return quality_step_guidance(step).running_summary


def quality_step_assistant_followup(step: str, *, blocked: bool = False) -> str:
    if step == "release" and blocked:
        return "Release remains blocked. Resolve the quality and execution evidence gaps before requesting release approval."
    return quality_step_guidance(step).assistant_followup

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
        assistant_followup="Next I will turn the approved scenario structure into executable test cases.",
    ),
    "cases": QualityStepGuidance(
        running_summary="Generating structured test cases",
        assistant_followup="Next I will generate a reviewable, versioned automation asset.",
    ),
    "verification_plan": QualityStepGuidance(
        running_summary="Generating verification plan",
        assistant_followup="Next I will turn the approved plan into executable, traceable test cases.",
    ),
    "automation": QualityStepGuidance(
        running_summary="Generating a reviewable automation asset",
        assistant_followup=(
            "The asset is ready. Provide or confirm the target environment URL before starting execution."
        ),
    ),
    "scope": QualityStepGuidance(
        running_summary="Generating test scope from system image context",
        assistant_followup="Next I will turn this scope into scenario coverage.",
    ),
    "change_document": QualityStepGuidance(
        running_summary="Generating traceable quality change document",
        assistant_followup="The change record is ready. Next I will assess release readiness from current evidence.",
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


def quality_step_assistant_followup(step: str) -> str:
    return quality_step_guidance(step).assistant_followup

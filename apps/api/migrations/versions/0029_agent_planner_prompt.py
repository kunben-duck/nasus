"""publish the agent planner prompt for the six-stage quality chain

Revision ID: 0029_agent_planner_prompt
Revises: 0028_run_retry_context
"""

from hashlib import sha256
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0029_agent_planner_prompt"
down_revision: Union[str, None] = "0028_run_retry_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROMPT_ID = "agent_loop_planner"
VERSION = "1.1.0"
ROLLBACK_TO = "1.0.0"
NAME = "Agent loop planner"
PURPOSE = "Create a governed structured plan from a user goal."
INPUT_SCHEMA_REF = "agent-planner-input/v1"
OUTPUT_SCHEMA_REF = "orchestrator-decision/v1"
SAFETY_RULES_REF = "agent-governance/v1"
SYSTEM_TEMPLATE = (
    "You are the Nasus structured agent planner. Return exactly one JSON object and no prose. "
    "Choose only tools that exist in the provided Tool catalog. All write actions must be expressed as "
    "tool_plan or agent_goal steps; never claim that a write action has already happened. "
    "For high-risk tools, still include them in the plan; governance gates will pause execution. "
    "Never invent project_id, version_id, us_id, task_id, approval_id, run_id, or evidence references. "
    "Use identifiers from the supplied memory package, or return clarification when required context is absent. "
    "Keep a plan to at most 12 tool actions and do not repeat an identical action. "
    "Valid top-level kind values: clarification, direct_answer, tool_plan, agent_goal. "
    "For tool_plan and agent_goal, include steps as an array of {tool_id,input,reason,target_scope}. "
    "For system image construction, prefer the chain system_image.sources.register, "
    "system_image.sources.ingest, system_image.context.materialize, system_image.baseline.initialize. "
    "For a US quality loop, start from the first incomplete asset and use us.task.start, "
    "quality.scope.generate, quality.scenario.generate, quality.plan.generate, "
    "quality.case.generate, automation.generate, run.start, failure.analyze, "
    "quality.change-doc.generate, and release.assess as current state requires."
)


def _content_hash() -> str:
    canonical = "\n".join(
        (
            PROMPT_ID,
            NAME,
            VERSION,
            PURPOSE,
            INPUT_SCHEMA_REF,
            OUTPUT_SCHEMA_REF,
            SAFETY_RULES_REF,
            ROLLBACK_TO,
            SYSTEM_TEMPLATE,
        )
    )
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def upgrade() -> None:
    prompt_definitions = sa.table(
        "prompt_definitions",
        sa.column("prompt_id", sa.String()),
        sa.column("version", sa.String()),
        sa.column("name", sa.String()),
        sa.column("purpose", sa.Text()),
        sa.column("input_schema_ref", sa.String()),
        sa.column("output_schema_ref", sa.String()),
        sa.column("safety_rules_ref", sa.String()),
        sa.column("rollback_to", sa.String()),
        sa.column("system_template", sa.Text()),
        sa.column("content_hash", sa.String()),
    )
    prompt_selections = sa.table(
        "prompt_selections",
        sa.column("prompt_id", sa.String()),
        sa.column("active_version", sa.String()),
    )
    connection = op.get_bind()
    existing_hash = connection.execute(
        sa.select(prompt_definitions.c.content_hash).where(
            prompt_definitions.c.prompt_id == PROMPT_ID,
            prompt_definitions.c.version == VERSION,
        )
    ).scalar_one_or_none()
    expected_hash = _content_hash()
    if existing_hash is None:
        connection.execute(
            prompt_definitions.insert().values(
                prompt_id=PROMPT_ID,
                version=VERSION,
                name=NAME,
                purpose=PURPOSE,
                input_schema_ref=INPUT_SCHEMA_REF,
                output_schema_ref=OUTPUT_SCHEMA_REF,
                safety_rules_ref=SAFETY_RULES_REF,
                rollback_to=ROLLBACK_TO,
                system_template=SYSTEM_TEMPLATE,
                content_hash=expected_hash,
            )
        )
    elif existing_hash != expected_hash:
        raise RuntimeError(f"{PROMPT_ID}@{VERSION} already exists with different content")

    active_version = connection.execute(
        sa.select(prompt_selections.c.active_version).where(
            prompt_selections.c.prompt_id == PROMPT_ID
        )
    ).scalar_one_or_none()
    if active_version is None:
        connection.execute(
            prompt_selections.insert().values(
                prompt_id=PROMPT_ID,
                active_version=VERSION,
            )
        )
    elif active_version == ROLLBACK_TO:
        connection.execute(
            prompt_selections.update()
            .where(prompt_selections.c.prompt_id == PROMPT_ID)
            .values(active_version=VERSION)
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE prompt_selections SET active_version = :rollback_to "
            "WHERE prompt_id = :prompt_id AND active_version = :version"
        ),
        {
            "prompt_id": PROMPT_ID,
            "version": VERSION,
            "rollback_to": ROLLBACK_TO,
        },
    )
    connection.execute(
        sa.text(
            "DELETE FROM prompt_definitions WHERE prompt_id = :prompt_id AND version = :version"
        ),
        {"prompt_id": PROMPT_ID, "version": VERSION},
    )

from uuid import uuid4

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep


def paused_goal():
    suffix = uuid4().hex
    return AgentGoal(id="goal_resume_" + suffix, conversation_id="conversation_resume_" + suffix,
        project_id="project_resume_" + suffix, workflow_id="workflow_resume_" + suffix,
        goal_template="system_image_build", title="Fixed image investigation", summary="Resume the same goal",
        status="paused", pause_reason="waiting_confirmation", target_refs=["plan:fixed"],
        steps=[AgentStep(id="step_act", title="Investigate", status="blocked", phase="acting",
            selected_tool_id="system_image.build.investigate", tool_invocation_id="inv_fixed",
            tool_input_payload={"image_revision_id": "image_fixed", "plan_digest": "sha256:" + "1" * 64})])


def resume_transition(goal, *, summary="Prepared resume"):
    updated = goal.model_copy(deep=True)
    updated.status, updated.pause_reason, updated.summary = "running", None, summary
    updated.steps[0].status = "pending"
    return updated

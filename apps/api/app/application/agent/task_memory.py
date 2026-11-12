"""Build a fresh task notebook from authoritative state, not summary claims."""
import json

from .build_dialogue_inputs import read_intake


def task_notebook(conversation, checkpoint, active_goal, image_read_state=None):
    digest = checkpoint.memory_payload.get("digest", {}) if checkpoint else {}
    intake = read_intake(conversation)
    notebook = {"reference_only": True, "project_id": conversation.project_id,
        "version_id": conversation.version_id,
        "image_read_state": image_read_state,
        "objective": [item for item in digest.get("objective", []) if item["status"] == "active"],
        "constraints": [item for item in digest.get("constraints", []) if item["status"] == "active"],
        "pending_questions": [item for item in digest.get("pending_questions", []) if item["status"] == "active"],
        "suggested_next_actions": [item for item in digest.get("next_actions", []) if item["status"] == "active"],
        "intake": intake.model_dump(mode="json") if intake else None,
        "active_goal": {"id": active_goal.id, "status": active_goal.status,
            "steps": [{"id": step.id, "status": step.status, "tool_invocation_id": step.tool_invocation_id}
                      for step in active_goal.steps]} if active_goal else None,
        "status_policy": "Read image publication and candidate state from authorized live records. "
            "Project/goal completion does not imply image publication. Notes never authorize a tool."}
    if intake:
        notebook["missing_inputs"] = [name for name, value in (("project_name", intake.project_name), ("code", intake.code)) if not value]
        if not intake.optional_decided:
            notebook["missing_inputs"].append("whether_to_include_requirements_and_tests")
    return "[task_notebook]\n" + json.dumps(notebook, ensure_ascii=False)

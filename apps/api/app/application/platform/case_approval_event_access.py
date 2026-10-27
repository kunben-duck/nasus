from ...domain.quality_loop.case_approval import CASE_APPROVAL_EVENT
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from .errors import PlatformApplicationError


class CaseApprovalEventAccess:
    """Authorize original admission events again when streaming or replaying."""

    def __init__(self, application, commands):
        self.application, self.commands = application, commands

    def can_access(self, event):
        if event.event_type != CASE_APPROVAL_EVENT:
            return True
        try:
            project = event.patch.get("project_id")
            if (not project or event.entity_type != "test_design_case_approval"
                    or event.patch.get("revision_id") != event.entity_id or event.correlation_id != project
                    or set(event.patch) != {"project_id", "revision_id", "status"}):
                raise ValueError("case admission event lost its fixed original resource")
            value = self.application.read(project, event.entity_id)
            revision = value["revision"]
            command = self.commands.get_invocation(revision["invocation_id"])
            if (command is None or command.conversation_id != event.conversation_id
                    or command.input_payload.get("agent_goal_id") != event.agent_goal_id
                    or revision["status"] != event.patch["status"] or event.mutation_kind != "append"
                    or event.query_keys != [["test-design-case-approvals", project]] or event.snapshot_hint is not True):
                raise ValueError("case admission event differs from its canonical fact")
            return True
        except (SourceAccessDenied, StaleSourceAccessScope):
            return False
        except PlatformApplicationError as error:
            if error.status_code == 403:
                return False
            raise
        except (ValueError, KeyError) as error:
            raise PlatformApplicationError("case_admission_event_invalid", "Original case admission event could not be verified.", 502) from error

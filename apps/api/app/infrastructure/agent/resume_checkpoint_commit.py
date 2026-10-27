from ...application.agent.agent_models import AgentGoal
from ...application.agent.resume_ports import AgentResumeCommitPort
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ..persistence.conversation_repository import ConversationRepository


class SQLAlchemyAgentResumeCommit(AgentResumeCommitPort):
    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    def commit_at_checkpoint(self, goal: AgentGoal, checkpoint: AgentResumeCheckpoint) -> None:
        self.repository.upsert_goal(goal, expected_resume=checkpoint)

    def is_consumed(self, checkpoint: AgentResumeCheckpoint) -> bool:
        return self.repository.is_resume_consumed(checkpoint)

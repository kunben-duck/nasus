"""Compose bounded-context claim receipts without replacing the existing fixture journal."""
from .http_fixture_preparation_repository import HttpFixturePreparationJournal
from .run_plan_case_preparation_repository import RunPlanCasePreparationJournal


class ToolClaimJournal:
    def __init__(self):
        self.journals = (HttpFixturePreparationJournal(), RunPlanCasePreparationJournal())

    def record(self, session, command):
        for journal in self.journals:
            journal.record(session, command)

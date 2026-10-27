from dataclasses import replace
import json

import pytest

from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.quality_loop.business_rules import BusinessRuleReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import AcceptanceIntegrityError, ObservableOracle, acceptance_identity, require_authority_decision
from apps.api.app.domain.quality_loop.business_rule import RULE_POLICY, RULE_TOOL, RULE_QUERY_TOOL, BusinessRuleRevision, business_rule_identity
from apps.api.tests.test_agent_evidence_observations import conversation


def test_business_rule_authority_does_not_alias_an_ac_or_another_image():
    rule_id = business_rule_identity("project", "image", "object")
    assert rule_id != acceptance_identity("project", "image", "object")
    assert rule_id != business_rule_identity("project", "next-image", "object")
    value = BusinessRuleRevision("r1", rule_id, "project", "image", "sha256:" + "a" * 64, "object", "binding", "source", "doc",
        "sha256:" + "b" * 64, "approved", None, 1, "reviewer", "invocation", "now", "sha256:" + "c" * 64)
    for change in ({"rule_id": acceptance_identity("project", "image", "object")}, {"policy_revision": "nasus.acceptance-authority.v1"},
                   {"status": "withdrawn"}, {"sequence": True}):
        with pytest.raises(AcceptanceIntegrityError):
            replace(value, **change)
    withdrawn = replace(value, revision_id="r2", previous_revision_id="r1", sequence=2, status="withdrawn")
    assert value.status == "approved" and withdrawn.digest != value.digest


def test_rule_confirmation_cannot_be_inferred_or_reused_from_ac_confirmation():
    oracle = ObservableOracle("Unauthenticated", "POST", "HTTP status", "401")
    require_authority_decision("approve", oracle, "user_confirmed_business_rule", None, required_basis="user_confirmed_business_rule")
    for basis in (None, "user_confirmed_requirement", "code_observed", "accepted_relation", "model_generated"):
        with pytest.raises(ValueError):
            require_authority_decision("approve", oracle, basis, None, required_basis="user_confirmed_business_rule")
    with pytest.raises(ValueError):
        BusinessRuleReviewInput(project_id="p", image_revision_id="i", image_artifact_hash="sha256:" + "a" * 64,
            object_id="o", basis_digest="sha256:" + "b" * 64, expected_previous_revision_id=None, policy_revision=RULE_POLICY,
            decision="approve", oracle=oracle.__dict__, authority_basis="user_confirmed_requirement", reason="Not a rule approval")


@pytest.mark.parametrize("title", ["Inspect business rule authority and withdraw approval", "检查业务规则批准，并撤回规则"])
def test_agent_can_discover_both_rule_tools(title):
    session = conversation()
    session.title = title
    selected = json.loads(compact_tool_catalog_json([*core_tool_definitions(), *system_image_tool_definitions()], session))["relevant_tools"]
    assert {RULE_TOOL, RULE_QUERY_TOOL} <= {item["tool_id"] for item in selected}

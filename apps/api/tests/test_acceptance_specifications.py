from dataclasses import replace

import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import (
    AcceptanceRevision, ObservableOracle, AcceptanceIntegrityError, acceptance_identity, require_authority_decision,
)
from apps.api.app.application.quality_loop.acceptance_specifications import OracleInput


def test_only_independently_confirmed_observable_oracle_can_be_approved():
    oracle = ObservableOracle("Logged in", "Submit empty query", "HTTP status", "400")
    require_authority_decision("approve", oracle, "user_confirmed_requirement", None)
    for value in (None, "model_generated", "code_observed", "accepted_relation"):
        with pytest.raises(ValueError):
            require_authority_decision("approve", oracle, value, None)
    with pytest.raises(ValueError):
        require_authority_decision("approve", None, "user_confirmed_requirement", None)
    for key in ("preconditions", "action", "observation", "expected_result"):
        fields = dict(preconditions="none", action="input", observation="status", expected_result="400")
        with pytest.raises(ValueError):
            OracleInput(**{**fields, key: " "})
        with pytest.raises(ValueError):
            ObservableOracle(**{**fields, key: "x" * 2001})


def test_withdrawal_does_not_erase_previous_authority_and_identity_never_transfers_images():
    require_authority_decision("withdraw", None, None, "approved")
    for prior in (None, "withdrawn"):
        with pytest.raises(ValueError):
            require_authority_decision("withdraw", None, None, prior)
    ac = acceptance_identity("project", "image", "object")
    assert ac != acceptance_identity("project", "next-image", "object")
    assert ac != acceptance_identity("other-project", "image", "object")
    value = AcceptanceRevision("r1", ac, "project", "image", "sha256:" + "a" * 64, "object", "binding", "source", "doc",
                               "sha256:" + "b" * 64, "approved", None, 1, "reviewer", "invocation", "now", "sha256:" + "c" * 64)
    with pytest.raises(AcceptanceIntegrityError):
        replace(value, status="withdrawn")
    next_value = replace(value, revision_id="r2", previous_revision_id="r1", sequence=2, status="withdrawn")
    assert next_value.digest != value.digest and value.status == "approved"


def test_agent_discovers_authority_tools_and_only_describes_authorized_metadata():
    import json
    from types import SimpleNamespace
    from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
    from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
    from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
    from apps.api.app.application.platform.tool_acceptance import ToolAcceptanceObservationApplicationService
    from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
    from apps.api.app.application.quality_loop.acceptance_specifications import AcceptanceAuthorityReceipt
    from apps.api.tests.test_agent_evidence_observations import conversation, Invocations, InvocationAccess
    session = conversation()
    session.title = "Inspect frozen oracle authority and withdraw requirement approval"
    tools = json.loads(compact_tool_catalog_json([*core_tool_definitions(), *system_image_tool_definitions()], session))["relevant_tools"]
    assert {"query.quality.acceptance_specification", "quality.acceptance_specification.review"} <= {t["tool_id"] for t in tools}
    request = dict(project_id="project", image_revision_id="image", image_artifact_hash="sha256:" + "a" * 64, object_id="ac")
    receipt = AcceptanceAuthorityReceipt(**request, ac_id=acceptance_identity("project", "image", "ac"), basis_digest="sha256:" + "b" * 64,
        head_revision_id=None, head_artifact_hash=None, status="unapproved")
    invocation = ToolInvocation(id="tool", tool_id="query.quality.acceptance_specification", status="completed", summary="verified",
        input_payload=request, result=ToolResult(invocation_id="tool", status="completed", summary="verified", acceptance_authority=receipt))
    calls = []
    observer = ToolAcceptanceObservationApplicationService(Invocations(invocation), SimpleNamespace(verify_receipt=lambda value: calls.append(value)), InvocationAccess())
    assert observer.describe("tool", "project") == receipt.model_dump(mode="json") and calls == [receipt]
    assert observation_receipt_fingerprint(invocation.result)
    with pytest.raises(Exception) as error:
        observer.describe("tool", "other-project")
    assert error.value.status_code == 403 and len(calls) == 1
    invocation.input_payload = {**request, "object_id": "forged"}
    with pytest.raises(Exception) as error:
        observer.describe("tool", "project")
    assert error.value.status_code == 409 and len(calls) == 1

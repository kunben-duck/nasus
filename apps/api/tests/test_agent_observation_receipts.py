from types import SimpleNamespace

from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.system_image.evidence_tool_models import EvidenceReadInput
from apps.api.app.application.system_image.evidence_tools import EvidenceToolApplicationService
from apps.api.app.application.system_image.image_query_models import ImagePageInput
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionPage
from apps.api.app.domain.system_image.image_revision import build_image_artifact
from apps.api.tests.test_agent_build_plans import graph_fixture
from apps.api.tests.test_image_revision import candidate, header
from apps.api.tests.test_source_evidence import service


def observe(goal, result, tool_id):
    invocation = ToolInvocation(id=result.invocation_id, tool_id=tool_id, status="completed",
                                summary=result.summary, result=result)
    LocalAgentGraphRuntime._record_observation_progress(goal, invocation, result.summary)


def test_image_pages_with_the_same_summary_are_distinct_observations():
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    pages = [ImageRevisionPage(header(payload), "members", (item,), 2, offset + 1 if offset == 0 else None)
             for offset, item in enumerate(payload["members"])]
    queries = ImageQueryToolApplicationService(SimpleNamespace(read=lambda **request: pages[request["offset"]]))
    receipts = [queries.execute(ImagePageInput(project_id="project", image_revision_id="image", section="members", offset=offset, limit=1))
                for offset in range(2)]
    assert receipts[0].result_hash != receipts[1].result_hash
    _, _, _, goal = graph_fixture()
    for offset, receipt in enumerate(receipts):
        result = ToolResult(invocation_id=f"page-{offset}", status="completed", summary="Frozen image query verified", image_query=receipt)
        observe(goal, result, "query.system_image.revisions.read")
        assert goal.no_progress_observations == 0
    # Changing an invocation ID does not turn a duplicate read into progress.
    observe(goal, result.model_copy(update={"invocation_id": "retry"}), "query.system_image.revisions.read")
    assert goal.no_progress_observations == 1


def test_archived_evidence_excerpt_receipts_distinguish_new_lines_without_persisting_text():
    queries, _, _ = service()
    tools = EvidenceToolApplicationService(queries)
    first = tools.read(EvidenceReadInput(project_id="project", source_revision_id="revision", evidence_id="evidence", max_lines=1))
    assert first.next_start_line is not None
    second = tools.read(EvidenceReadInput(project_id="project", source_revision_id="revision", evidence_id="evidence",
                                          start_line=first.next_start_line, max_lines=1))
    _, _, _, goal = graph_fixture()
    signatures = []
    for receipt in (first, second):
        result = ToolResult(invocation_id="read", status="completed", summary="Evidence verified", evidence_query=receipt)
        signatures.append(observation_receipt_fingerprint(result))
        observe(goal, result, "query.system_image.evidence.read")
        assert goal.no_progress_observations == 0
    assert signatures[0] != signatures[1] and all(len(signature) == 64 for signature in signatures)
    observe(goal, result, "query.system_image.evidence.read")
    assert goal.no_progress_observations == 1
    assert observation_receipt_fingerprint(result.model_copy(update={"status": "failed"})) is None
    assert observation_receipt_fingerprint(None) is None


def test_index_preview_observations_are_stable_but_change_with_model_consent():
    result = ToolResult(invocation_id="first", status="completed", summary="Index preview",
        index_preview={"request": {"input_digest": "input", "model_config_digest": "model-v1"}})
    first = observation_receipt_fingerprint(result)
    assert first == observation_receipt_fingerprint(result.model_copy(update={"invocation_id": "second"}))
    changed = result.model_copy(update={"index_preview": {"request": {"model_config_digest": "model-v2", "input_digest": "input"}}})
    assert first != observation_receipt_fingerprint(changed)
    assert observation_receipt_fingerprint(changed.model_copy(update={"status": "failed"})) is None

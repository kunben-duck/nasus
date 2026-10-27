import copy

from apps.api.app.main import app
from apps.api.app.domain.system_image.context_pack import canonical_bytes, budget_context
from apps.api.app.domain.system_image.context_partition import PARTITION_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_context_packs_api import acceptance, documents, evidence_api, archive, preview, read
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import completed, invoke


def test_partitioned_preview_canonical_archive_and_legacy_replay(acceptance, monkeypatch):
    v = acceptance
    legacy, legacy_url = read(v, completed(archive(v)[0]))
    v["requirement_path"].write_text("# US-17 Search\n## Acceptance criteria\n" + "\n".join(
        f"AC-{n}: Search boundary {n}. " + "Retain the complete expected observation. " * 8 for n in range(1, 7))
        + "\n## Business rules\nBR-1: Never disclose credentials.\nBR-2: Isolate fixture data.\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    v["ac_query"].update(image_revision_id=image["image_revision_id"], image_artifact_hash=image["artifact_hash"])
    large = preview(v, policy_revision=PARTITION_POLICY, max_tokens=32768, candidate_limit=1)
    assert len(large["context"]["required_constraints"]) == 8
    globals_ = [c for c in large["context"]["required_constraints"] if c["kind"] == "business_rule"]
    targets = [c for c in large["context"]["required_constraints"] if c["kind"] == "acceptance_criterion"]
    # Choose a real byte ceiling that fits any individual AC plus both global
    # rules, but not all six. The HTTP response is still measured independently.
    ceilings = []
    for target in targets:
        body = copy.deepcopy(large["context"]["parts"][0]["context"])
        body["required_constraints"] = [c for c in body["required_constraints"] if c in globals_ or c == target]
        body["partition"]["target_object_ids"] = [target["object_id"]]
        ceilings.append(budget_context(body, [], 32768)["budget"]["used_upper_bound"])
    ceiling = max(ceilings) + 100
    view = preview(v, policy_revision=PARTITION_POLICY, max_tokens=ceiling, candidate_limit=1)
    assert len(view["context"]["parts"]) > 1
    all_targets = []
    for part in view["context"]["parts"]:
        body = part["context"]
        assert len(canonical_bytes(body)) == body["budget"]["used_upper_bound"] <= ceiling
        assert snapshot_digest(body) == part["part_id"]
        assert [c for c in body["required_constraints"] if c["kind"] == "business_rule"] == globals_
        all_targets.extend(body["partition"]["target_object_ids"])
    assert all_targets == [c["object_id"] for c in targets]
    done = completed(archive(v, view)[0])
    stored, url = read(v, done)
    assert stored["context"] == view["context"] and stored["metadata"]["mandatory_count"] == 8
    assert stored["current_use"]["generation_authorized"] is False
    receipt = completed(invoke(v, "query.system_image.context.preview", view["request"]))["result"]["context_pack"]
    assert receipt["mandatory_count"] == 8 and "Never disclose" not in str(receipt)
    assert v["client"].get(legacy_url, headers=v["headers"]).json() == legacy
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.read
    def missing_global(*args):
        value = original(*args)
        value["context"]["parts"][0]["context"]["required_constraints"].pop()
        return value
    monkeypatch.setattr(artifacts, "read", missing_global)
    denied = v["client"].get(url, headers=v["headers"])
    assert denied.status_code == 502 and "credentials" not in denied.text


def test_v2_cannot_rebind_a_v1_preview_digest_or_hide_indivisible_overflow(acceptance):
    v = acceptance
    old = preview(v)
    switched = {**old, "request": {**old["request"], "policy_revision": PARTITION_POLICY}}
    assert archive(v, switched)[0].json()["result"]["followup_reason"] == "context_inputs_changed"
    params = {k: value for k, value in v["ac_query"].items() if k != "object_id"}
    denied = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/context-packs/preview",
        headers=v["headers"], params={**params, "policy_revision": PARTITION_POLICY, "max_tokens": 512})
    assert denied.status_code == 422 and denied.json()["detail"]["error"]["code"] == "mandatory_context_over_budget"


def test_fresh_context_queries_once_per_relation_but_archive_reads_replay(acceptance, monkeypatch):
    from apps.api.app.application.system_image.image_query_models import ImageScreenedCandidatesInput

    v = acceptance
    queries = app.state.container.context_packs.sources.image_queries
    counts = {"read": 0, "expand": 0}
    read_query, expand = queries._read, queries.expand
    def count_read(request):
        if isinstance(request, ImageScreenedCandidatesInput):
            counts["read"] += 1
        return read_query(request)
    def count_expand(receipt):
        counts["expand"] += 1
        return expand(receipt)
    monkeypatch.setattr(queries, "_read", count_read)
    monkeypatch.setattr(queries, "expand", count_expand)
    view = preview(v, policy_revision=PARTITION_POLICY)
    assert counts == {"read": 2, "expand": 0}
    counts.update(read=0, expand=0)
    done = completed(archive(v, view)[0])
    assert counts == {"read": 4, "expand": 0}
    counts.update(read=0, expand=0)
    value, _ = read(v, done)
    assert value["context"] == view["context"]
    assert counts == {"read": 2, "expand": 2}


def test_verified_image_session_is_query_local_copy_isolated_and_rechecks_access(acceptance, monkeypatch):
    import pytest
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.domain.system_image.source_access import SourceAccessRule, SourceAccessDenied
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
    from apps.api.tests.test_source_access_api import grant_member

    v = acceptance
    images = app.state.container.context_packs.sources.images
    reads = []
    original = images.artifacts.read
    def counted(*args):
        reads.append(args)
        return original(*args)
    monkeypatch.setattr(images.artifacts, "read", counted)
    args = (v["project_id"], v["ac_query"]["image_revision_id"])
    grant_member(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with images.verified_read_session():
            _, first = images.frozen_snapshot(*args)
            first["objects"].clear()
            assert images.frozen_snapshot(*args)[1]["objects"]
            assert len(reads) == 1
        images.frozen_snapshot(*args)
        assert len(reads) == 2
        with images.verified_read_session():
            images.frozen_snapshot(*args)
            with actor_scope(UserProfile.model_validate(v["member"])):
                images.frozen_snapshot(*args)
            assert len(reads) == 4  # Another actor cannot reuse the owner's bytes.
            original_get = images.repository.get
            def changed_membership(*args):
                header, ref, bindings = original_get(*args)
                return header, ref, frozenset(sorted(bindings)[1:])
            with monkeypatch.context() as patch:
                patch.setattr(images.repository, "get", changed_membership)
                with pytest.raises(ImageRevisionIntegrityError):
                    images.frozen_snapshot(*args)
    with actor_scope(UserProfile.model_validate(v["member"])):
        with images.verified_read_session():
            images.frozen_snapshot(*args)
            repo = SourceAccessRepository()
            snapshot = repo.load_snapshot(v["project_id"])
            repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="partition-cache-revoke")
            with pytest.raises(SourceAccessDenied):
                images.frozen_snapshot(*args)

"""Full source selection and original pins; inputs are explicit protocol specimens."""
import asyncio
from contextvars import copy_context
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image import image_revision_queries as queries
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_image_selection_copies import reader


METHODS = ("bindings", "automation_bindings", "run_plan_sources")


def prepared(summary):
    return {"project_id": summary.project_id, "context_pin": {
        "image_revision_id": summary.image_revision_id, "image_artifact_hash": summary.artifact_hash},
        "context": {"source_manifest_id": summary.manifest_id, "source_manifest_hash": summary.manifest_hash}}


@pytest.mark.parametrize("method", METHODS)
def test_generation_inventory_does_not_copy_or_expose_the_complete_image(monkeypatch, method):
    images, payload, state = reader()
    summary, full = images.frozen_snapshot("project", "image")
    request = prepared(summary)
    inventory = ImageGenerationSourceInventory(images)
    original_copy = queries.deepcopy
    copies = []

    def copied(value):
        if type(value) is dict and value.get("schema") == payload["schema"]:
            copies.append(value)
        return original_copy(value)

    with inventory.verified_read_session():
        images.frozen_snapshot("project", "image")
        monkeypatch.setattr(queries, "deepcopy", copied)
        before = state.authority
        actual = getattr(inventory, method)(request)
        assert copies == [] and state.authority > before
        if method == "run_plan_sources":
            assert actual == {"project_id": "project", "image_revision_id": "image",
                "image_artifact_hash": summary.artifact_hash, "manifest_id": summary.manifest_id,
                "manifest_hash": summary.manifest_hash, "source_members": full["source_members"]}
            assert type(actual["source_members"]) is list
            actual["source_members"][0].clear()
            assert inventory.run_plan_sources(request)["source_members"] == full["source_members"]
        else:
            assert actual == ("binding",)
    assert images._current_verified_reads() is None


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("field", ["artifact_hash", "project_id", "image_revision_id"])
def test_generation_inventory_rejects_mixed_image_pins(method, field):
    images, _payload, _state = reader()
    summary, members = images.frozen_snapshot("project", "image")
    request = prepared(summary)
    wrong = replace(summary, **{field: "sha256:" + "0" * 64 if field == "artifact_hash" else "foreign"})
    port = SimpleNamespace(frozen_source_members=lambda *_: (wrong, tuple(deepcopy(members["source_members"]))))
    with pytest.raises(ImageRevisionIntegrityError):
        getattr(ImageGenerationSourceInventory(port), method)(request)


@pytest.mark.parametrize("field", ["source_manifest_id", "source_manifest_hash"])
def test_model_egress_inventory_keeps_the_original_manifest_pin(field):
    images, _payload, _state = reader()
    summary, _ = images.frozen_snapshot("project", "image")
    request = prepared(summary)
    request["context"][field] = "foreign"
    with pytest.raises(ImageRevisionIntegrityError):
        ImageGenerationSourceInventory(images).bindings(request)


def test_complete_source_inventory_preserves_optional_gaps_and_captured_binding_order():
    images, _payload, _state = reader()
    summary, _ = images.frozen_snapshot("project", "image")
    members = [{"binding_id": "z-code", "source_type": "code", "source_revision_id": "code-v1", "status": "captured"},
        {"binding_id": "a-cases", "source_type": "test_asset", "source_revision_id": "cases-v1", "status": "captured"},
        {"binding_id": "missing-us", "source_type": "us_doc", "source_revision_id": None, "status": "failed"},
        {"binding_id": "pending-us", "source_type": "us_doc", "source_revision_id": None, "status": "pending"},
        {"binding_id": "legacy-us", "source_type": "us_doc", "source_revision_id": None, "status": "legacy_unverified"}]
    calls = []

    def sources(*args):
        calls.append(args)
        return summary, tuple(deepcopy(members))

    inventory = ImageGenerationSourceInventory(SimpleNamespace(frozen_source_members=sources))
    request = prepared(summary)
    assert inventory.bindings(request) == inventory.automation_bindings(request) == ("a-cases", "z-code")
    assert inventory.run_plan_sources(request)["source_members"] == members
    assert calls == [("project", "image")] * 3


@pytest.mark.parametrize("method", METHODS)
def test_each_inventory_still_rechecks_live_authority_in_an_owned_scope(method):
    images, _payload, state = reader()
    summary, _ = images.frozen_snapshot("project", "image")
    inventory = ImageGenerationSourceInventory(images)
    with inventory.verified_read_session():
        getattr(inventory, method)(prepared(summary))
        state.allowed = False
        before = state.authority
        with pytest.raises(SourceAccessDenied):
            getattr(inventory, method)(prepared(summary))
        assert state.authority > before
    assert images._current_verified_reads() is None


def test_source_selection_cannot_inherit_parent_proof_ownership():
    images, _payload, state = reader()

    async def verify():
        with images.verified_read_session():
            expected = images.frozen_source_members("project", "image")
            owner = images._verified_read_scope.get()

            async def child():
                assert images._current_verified_reads() is None
                assert images.frozen_source_members("project", "image") == expected

            await asyncio.create_task(child())
            assert state.artifacts == 2 and owner.is_current
            context = copy_context()
            assert await asyncio.to_thread(context.run, images.frozen_source_members, "project", "image") == expected
            assert state.artifacts == 3 and owner.is_current
            assert images.frozen_source_members("project", "image") == expected
            assert state.artifacts == 3
        assert not owner.is_open and images._current_verified_reads() is None

    asyncio.run(verify())


def test_revocation_during_source_projection_returns_no_inventory(monkeypatch):
    images, _payload, state = reader()
    original = queries.deepcopy
    with images.verified_read_session():
        images.frozen_snapshot("project", "image")

        def revoke(value):
            result = original(value)
            if type(value) is tuple and value and "binding_id" in value[0]:
                state.allowed = False
            return result

        monkeypatch.setattr(queries, "deepcopy", revoke)
        with pytest.raises(SourceAccessDenied):
            images.frozen_source_members("project", "image")
        assert state.artifacts == 1
    assert images._current_verified_reads() is None

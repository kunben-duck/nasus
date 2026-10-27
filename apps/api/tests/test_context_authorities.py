from copy import deepcopy
from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.context_authorities import (
    ContextAuthorityDependency, archived_authority_pins, dependency_root,
)
from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError


def payload():
    pin = {"object_id": "ac", "basis_digest": "sha256:" + "1" * 64,
        "revision_id": "approved-revision", "artifact_hash": "sha256:" + "2" * 64, "status": "approved"}
    return {"provenance": {"authority_pins": [deepcopy(pin)]}, "context": {"required_constraints": [
        {"object_id": "ac", "authority": deepcopy(pin), "source_fields": [{"name": "acceptance_criterion"}]}]}}


def dependency():
    return ContextAuthorityDependency("project", "context", "ac", "acceptance", "sha256:" + "1" * 64,
        "approved", "approved-revision", "sha256:" + "2" * 64, "sha256:" + "3" * 64, "image", "sha256:" + "4" * 64)


def test_original_pins_preserve_exact_revision_kind_and_negative_dependencies():
    raw = payload()
    before = deepcopy(raw)
    pin, = archived_authority_pins(raw)
    assert pin["kind"] == "acceptance" and pin["revision_id"] == "approved-revision" and raw == before
    for obj in (raw["provenance"]["authority_pins"][0], raw["context"]["required_constraints"][0]["authority"]):
        obj.update(status="unapproved", revision_id=None, artifact_hash=None)
    assert archived_authority_pins(raw)[0]["revision_id"] is None
    negative = replace(dependency(), status="unapproved", revision_id=None, artifact_hash=None, authority_registration_hash=None)
    assert negative.record_v1["content_hash"] != dependency().record_v1["content_hash"]


@pytest.mark.parametrize("damage", ["duplicate", "omit", "wrong_kind", "extra", "alter_constraint", "negative_with_revision"])
def test_missing_duplicate_or_fabricated_archive_pins_are_rejected(damage):
    raw = payload()
    pin = raw["provenance"]["authority_pins"][0]
    if damage == "duplicate":
        raw["provenance"]["authority_pins"].append(deepcopy(pin))
    elif damage == "omit":
        raw["provenance"]["authority_pins"] = []
    elif damage == "wrong_kind":
        raw["context"]["required_constraints"][0]["source_fields"][0]["name"] = "test_title"
    elif damage == "extra":
        pin["oracle"] = "invented expected result"
    elif damage == "alter_constraint":
        raw["context"]["required_constraints"][0]["authority"]["revision_id"] = "latest-head"
    else:
        pin["status"] = "unapproved"
        raw["context"]["required_constraints"][0]["authority"] = deepcopy(pin)
    with pytest.raises(ContextPackIntegrityError):
        archived_authority_pins(raw)


def test_root_hash_pins_the_entire_set_and_registration_not_private_oracle_body():
    metadata = {"project_id": "project", "context_id": "context", "image_revision_id": "image",
        "image_artifact_hash": "sha256:" + "5" * 64, "input_digest": "sha256:" + "6" * 64,
        "artifact_hash": "sha256:" + "7" * 64, "invocation_id": "compile"}
    args = dict(invocation_id="register", actor_id="reviewer", recorded_at="time")
    root = dependency_root(metadata, "sha256:" + "8" * 64, (dependency(),), **args)
    assert dependency().record_v1["content_hash"] == "sha256:f022ee20fcbd37badd3c14dcd0a48ab035370ff5fb0600dea06ac77d1e44c670"
    assert root["content_hash"] == "sha256:0da6a1792624546f87129712a4b6cbe99dd23ac77e5b3333cc127c36a1414251"
    assert root["authority_count"] == 1 and root["invocation_id"] == "compile"
    assert root["registration_invocation_id"] == "register"
    assert dependency_root(metadata, "sha256:" + "8" * 64, (), **args)["content_hash"] != root["content_hash"]
    assert not any(word in repr(root) for word in ("expected_result", "source_fields", "s3://"))
    with pytest.raises(ContextPackIntegrityError):
        dependency_root(metadata, "sha256:" + "8" * 64, (replace(dependency(), project_id="other"),), **args)
    with pytest.raises(ContextPackIntegrityError):
        dependency_root(metadata, "sha256:" + "8" * 64, (dependency(),), **{**args, "actor_id": ""})

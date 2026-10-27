from dataclasses import asdict, dataclass, replace

import pytest

from apps.api.app.domain.system_image.automation_provenance import (
    AutomationProvenance, AUTOMATION_PROVENANCE_POLICY, MAX_SCRIPT_PARENTS,
)
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


H = "sha256:" + "a" * 64
J = "sha256:" + "b" * 64


def script():
    parents = tuple((key, H, J) for key in (
        "case:g/c", "context:ctx", "coverage:g", "generation:g", "mapping:m", "scope:s"))
    return AutomationProvenance("project", "ctx", "script", "draft", H, "command", H, H, parents)


def test_script_provenance_pins_all_upstream_kinds_without_granting_authority():
    value = script()
    assert value.key == "script:draft"
    assert value.content_hash == snapshot_digest(value.payload_v1)
    assert value.payload_v1["policy_revision"] == AUTOMATION_PROVENANCE_POLICY
    assert not {"approved", "execution_authorized", "coverage", "source_text", "oracle"} & value.payload_v1.keys()
    assert snapshot_digest(value.payload_v1) != snapshot_digest({**value.payload_v1, "parents": []})


@pytest.mark.parametrize("field,value", [
    ("project_id", "other"), ("context_id", "other"), ("artifact_id", "other"),
    ("invocation_id", "other"), ("artifact_hash", J), ("fact_hash", J), ("origin_hash", J),
])
def test_identity_fact_origin_and_artifact_changes_cannot_reuse_registration(field, value):
    original = script()
    parents = original.parents
    if field == "context_id":
        parents = tuple(("context:other" if key == "context:ctx" else key, a, r) for key, a, r in parents)
    assert replace(original, **{field: value, "parents": parents}).content_hash != original.content_hash


@pytest.mark.parametrize("index", [1, 2])
def test_parent_artifact_and_registration_hashes_are_independently_pinned(index):
    original = script()
    parents = [list(pin) for pin in original.parents]
    parents[0][index] = J if parents[0][index] == H else H
    assert replace(original, parents=tuple(tuple(pin) for pin in parents)).content_hash != original.content_hash


@pytest.mark.parametrize("kind", ["case", "context", "coverage", "generation", "mapping", "scope"])
def test_every_required_parent_is_mandatory(kind):
    with pytest.raises(ValueError):
        replace(script(), parents=tuple(pin for pin in script().parents if not pin[0].startswith(kind + ":")))


@pytest.mark.parametrize("parents", [(), [], (("case:g/c", H, "bad"),),
    tuple(reversed(script().parents)), script().parents + (script().parents[-1],),
    tuple(sorted(script().parents + (("script:draft", H, H),))),
    tuple(sorted(script().parents + (("unknown:x", H, H),))),
    tuple(("context:other" if key == "context:ctx" else key, a, r) for key, a, r in script().parents),
])
def test_missing_foreign_duplicate_unsorted_or_malformed_ancestry_is_rejected(parents):
    with pytest.raises(ValueError):
        replace(script(), parents=parents)


@pytest.mark.parametrize("kind", [None, True, "", "run", "execution"])
def test_wrong_kind_cannot_become_execution_provenance(kind):
    with pytest.raises(ValueError):
        replace(script(), kind=kind)


def test_empty_parent_identity_is_not_a_valid_case_reference():
    with pytest.raises(ValueError):
        replace(script(), parents=tuple(("case:" if key.startswith("case:") else key, a, r)
            for key, a, r in script().parents))


def test_all_512_selected_cases_are_registered_without_the_128_impact_truncation():
    parents = tuple(sorted((*(pin for pin in script().parents if not pin[0].startswith("case:")),
        *(("case:g/c" + str(i), H, J) for i in range(512)))))
    value = replace(script(), parents=parents)
    assert len(value.parents) == MAX_SCRIPT_PARENTS == 517
    with pytest.raises(ValueError):
        replace(value, parents=tuple(sorted(value.parents + (("case:g/extra", H, H),))))


def test_review_and_withdrawal_use_exact_script_and_predecessor_not_latest_heads():
    original = script()
    pin = (original.key, original.artifact_hash, original.content_hash)
    first = AutomationProvenance("project", "ctx", "script_review", "review1", H, "review-command", H,
        original.content_hash, (pin,))
    second = replace(first, artifact_id="review2", invocation_id="withdraw-command",
        parents=tuple(sorted((pin, (first.key, first.artifact_hash, first.content_hash)))))
    assert first.content_hash != second.content_hash
    for parents in ((), (("mapping:m", H, H),), (pin, pin), ((second.key, H, H),)):
        with pytest.raises(ValueError):
            replace(second, parents=parents)


def test_future_fields_do_not_rewrite_the_versioned_provenance_digest():
    original = script()

    @dataclass(frozen=True)
    class FutureProvenance(AutomationProvenance):
        future_field: str = "excluded from the v1 hash"

    extended = FutureProvenance(**asdict(original))
    assert extended.content_hash == original.content_hash
    assert extended.payload_v1 == original.payload_v1

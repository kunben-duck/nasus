from copy import deepcopy

import pytest

from apps.api.app.domain.system_image.document_components import component_payloads, validate_component_payload
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_document_projection import extract, unit


def projected(text, path="requirements.md"):
    source = unit(text, path)
    result = []
    for parent in extract(text, path=path).observations:
        payload = {**parent.payload(text, source.content_hash), "project_id": "project", "source_id": "source",
                   "source_manifest_hash": "sha256:" + "a" * 64}
        result.extend((parent, payload, key, child) for key, child in component_payloads(parent, payload, text))
    return result


def test_criteria_and_rules_have_parent_qualified_identities_and_exact_continuations():
    text = "# US-1 Search\n## Acceptance criteria\nAC-1: Empty input fails.\nReturn HTTP 400.\n- AC-2: Valid search succeeds.\n## Business rules\nBR-1: Only authenticated users.\n## Notes\nNot part of the rule.\n"
    rows = projected(text)
    assert [row[3]["external_id"] for row in rows] == ["AC-1", "AC-2", "BR-1"]
    assert rows[0][3]["parent"]["field_indices"] == [0, 1]
    assert rows[0][3]["locator"]["start_line"] == 3 and rows[0][3]["locator"]["end_line"] == 4
    assert rows[2][3]["kind"] == "business_rule"
    for parent, body, key, child in rows:
        assert child["authority_status"] == "pending_confirmation"
        assert child["parent"]["relation"] == "source_contains"
        assert child["parent"]["payload_hash"] == snapshot_digest(body)
        assert validate_component_payload(child, body, snapshot_digest(parent.identity_key)) == key
    moved = projected("\n\n" + text.replace("400", "422"), "moved.md")
    assert [row[2] for row in moved] == [row[2] for row in rows]
    assert moved[0][3] != rows[0][3]
    other_parent = projected(text.replace("US-1", "US-2"))
    assert other_parent[0][2] != rows[0][2]


def test_duplicate_ac_ids_are_not_merged_and_unlabelled_bullets_use_occurrence_identity():
    rows = projected("# US-1 Search\n## 验收条件\n- AC-1: First.\n- AC-1: Different.\n- Anonymous one.\n- Anonymous two.\n## 业务规则\nRULE-1: Rule text.\n")
    assert len(rows) == 5
    assert rows[0][2] != rows[1][2]
    assert all(row[3]["identity_status"] == "ambiguous" and "duplicate_component_id" in row[3]["gaps"] for row in rows[:2])
    assert all(row[3]["identity_status"] == "source_occurrence" for row in rows[2:4])
    assert rows[4][3]["kind"] == "business_rule"


def test_ambiguous_parent_does_not_grant_stable_component_identity():
    rows = projected("# US-1 First\nAcceptance criteria: AC-1: First.\n# US-1 Other\nAcceptance criteria: AC-1: Other.\n")
    assert len(rows) == 2 and rows[0][2] != rows[1][2]
    assert all(row[3]["identity_status"] == "source_occurrence" and "parent_identity_not_unique" in row[3]["gaps"] for row in rows)


def test_unlabelled_prose_fenced_examples_and_test_oracles_are_not_promoted():
    assert not projected("# US-1 Search\nDescription: AC-1: example.\n```\nAcceptance criteria: forged\n```\n")
    assert not projected("Ordinary prose: must work.")
    assert not projected("# TC-1 Test\nExpected result: AC-1: successful.\n")


def test_nested_explicit_ac_headings_preserve_continuations_without_swallowing_notes():
    rows = projected("# US-1 Search\n## Acceptance criteria\n### AC-1: Empty input\nReturn 400.\n"
                     "### AC-2: Success\nReturn results.\n## Notes\nNot an oracle.\n")
    assert len(rows) == 2
    assert [item[3]["external_id"] for item in rows] == ["AC-1", "AC-2"]
    assert all(len(item[3]["fields"]) == 2 for item in rows)
    assert "Not an oracle" not in str([item[3] for item in rows])


@pytest.mark.parametrize("change", [
    lambda p: p.update(kind="approved_specification"),
    lambda p: p.update(authority_status="approved"),
    lambda p: p["parent"].update(relation="implements"),
    lambda p: p["parent"].update(field_indices=[1]),
    lambda p: p["parent"].update(payload_hash="sha256:" + "b" * 64),
    lambda p: p["fields"][0].update(value="Forged expectation"),
    lambda p: p.update(project_id="another"),
    lambda p: p.update(approved_by="forged"),
])
def test_parent_binding_and_child_semantics_cannot_be_forged(change):
    parent, payload, _, child = projected("# US-1 Search\nAcceptance criteria: AC-1: required\n")[0]
    child = deepcopy(child)
    change(child)
    with pytest.raises(ValueError):
        validate_component_payload(child, payload, snapshot_digest(parent.identity_key))


def test_multiline_csv_field_is_preserved_without_inventing_semantic_segmentation():
    rows = projected('id,title,acceptance_criteria,business_rules\nUS-1,Search,"AC-1: First\nAC-2: Second",BR-1: Login\n', "spec.csv")
    assert len(rows) == 2
    assert "compound_source_field_not_decomposed" in rows[0][3]["gaps"]
    assert rows[0][3]["identity_status"] == "source_occurrence" and rows[0][3]["external_id"] is None
    assert "AC-2" in rows[0][3]["fields"][0]["value"]
    assert rows[0][3]["locator"]["start_line"] == 2 and rows[0][3]["locator"]["end_line"] == 3


def test_component_limits_include_children_and_invalid_ids_are_reported_without_partial_file():
    source = "# US-1 Header\n## Acceptance criteria\nAC-" + "x" * 129 + ": invalid\n"
    result = extract(source)
    assert not result.observations and result.files[0]["status"] == "failed"
    text = "".join(f"# US-{i} Header\nAcceptance criteria: AC-1: Works.\n" for i in range(501))
    with pytest.raises(ValueError, match="entity limit"):
        extract(text)

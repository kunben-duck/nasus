from dataclasses import replace

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.domain.system_image.document_projection import DocumentField, disambiguate_documents
from apps.api.app.domain.system_image.evidence import text_digest
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor


def unit(text, path="requirements.md"):
    return SourceTextUnit(path, text, len(text.encode()), text_digest(text))


def extract(text, source_type="us_doc", path="requirements.md"):
    return ExplicitDocumentExtractor().extract(source_type, [unit(text, path)])


def test_requirement_ac_and_test_oracle_keep_line_evidence_and_reference_semantics():
    requirement = unit("# US-17 Search\nDescription: search catalog\n## Acceptance criteria\nAC-1: Empty input returns 400.\n")
    result = ExplicitDocumentExtractor().extract("us_doc", [requirement])
    row, = result.observations
    payload = row.payload(requirement.text, requirement.content_hash)
    assert row.kind == "requirement" and row.external_id == "US-17" and not row.gaps
    assert payload["fields"][-1]["name"] == "acceptance_criterion"
    assert payload["fields"][-1]["start_line"] == 4
    assert payload["fields"][-1]["snippet_hash"] == text_digest("AC-1: Empty input returns 400.\n")
    testcase, = extract("# TC-1 Search\nReferences: US-17\nPreconditions: login\nSteps: POST /search\nExpected result: HTTP 400\n",
                        "test_asset", "tests.md").observations
    assert testcase.references == ("US-17",) and testcase.gaps == ()
    assert testcase.payload("# TC-1 Search\nReferences: US-17\nPreconditions: login\nSteps: POST /search\nExpected result: HTTP 400\n",
                           requirement.content_hash)["reference_semantics"] == "references_only_not_asserts_or_implements"


def test_chinese_labels_missing_oracle_duplicates_and_line_moves():
    text = "# TC-2 查询\n需求引用：US-17\n测试步骤：请求查询接口\n"
    row, = extract(text, "test_asset").observations
    assert row.references == ("US-17",) and "missing_expected_result" in row.gaps
    moved, = extract("\n\n" + text, "test_asset").observations
    assert row.identity_key == moved.identity_key and row.start_line != moved.start_line
    duplicate = disambiguate_documents((row, replace(row, relative_path="other.md")))
    assert all(item.identity_status == "ambiguous" for item in duplicate)
    assert duplicate[0].identity_key != duplicate[1].identity_key


def test_csv_multiline_rows_and_no_formula_execution():
    text = 'id,title,steps,expected_result,requirement_ids\r\nTC-9,Search,"1. Open\n2. Submit",=NOT_EXECUTED(),US-17\r\n'
    row, = extract(text, "test_asset", "cases.csv").observations
    assert row.start_line == 2 and row.end_line == 3 and row.references == ("US-17",)
    assert row.fields[1].value == "=NOT_EXECUTED()"
    payload = row.payload(text, text_digest(text))
    assert payload["fields"][0]["snippet_hash"] == text_digest('TC-9,Search,"1. Open\n2. Submit",=NOT_EXECUTED(),US-17\r\n')


@pytest.mark.parametrize("text", ["title,steps\nA,B", "id,id,title\nTC-1,TC-1,A", 'id,title\nTC-1,"unclosed', "id,title\nUS-1,Wrong kind"])
def test_malformed_csv_is_explicit_failed_not_parsed(text):
    result = extract(text, "test_asset", "cases.csv")
    assert not result.observations and result.files[0]["status"] == "failed"


def test_unsupported_flattened_binary_and_script_do_not_invent_line_evidence():
    for path in ("spec.docx", "cases.xlsx", "spec.pdf", "test_search.js"):
        result = extract("# US-1 Header", path=path)
        assert not result.observations and result.files[0]["status"] == "unsupported"
    result = ExplicitDocumentExtractor().extract("us_doc", [replace(unit("# US-1 Header"), text_is_lossless=False)])
    assert not result.observations


def test_fenced_ids_are_not_declarations_and_anonymous_document_is_not_a_requirement():
    result = extract("```text\n# US-1 Example\n```\nOrdinary prose.\n")
    row, = result.observations
    assert row.kind == "requirement_document" and row.external_id is None
    assert "no_explicit_record_identity" in row.gaps


@pytest.mark.parametrize("fence,inner", [("````", "```"), ("~~~~", "~~~"), ("```", "~~~"), ("```", "``` not a closing fence")])
def test_nested_or_nonclosing_fences_cannot_promote_example_requirements_or_oracles(fence, inner):
    text = f"# US-1 Actual\n{fence}\n{inner}\n# US-2 Fake\nAcceptance criteria: not an oracle\n{fence}\nDescription: actual description\n"
    row, = extract(text).observations
    assert row.external_id == "US-1" and "missing_acceptance_criterion" in row.gaps
    assert all(field.name == "description" for field in row.fields)


def test_indented_examples_and_overlong_identity_are_not_records():
    row, = extract("    # US-1 Code example\n    Acceptance criteria: illustrative only\n").observations
    assert row.kind == "requirement_document"
    result = extract("# US-" + "a" * 129 + " Title\nDescription: x\n")
    assert not result.observations and result.files[0]["status"] == "failed"
    for text, path in (("# US-1 Title\nDescription: " + '"' * 17000, "requirements.md"),
                       ("# US-1 Title\nDescription: x", "a/" * 520 + "requirements.md")):
        result = extract(text, path=path)
        assert not result.observations and result.files[0]["status"] == "failed"


def test_bounds_and_duplicate_paths_are_not_silently_truncated():
    with pytest.raises(ValueError, match="duplicate"):
        ExplicitDocumentExtractor().extract("us_doc", [unit("text"), unit("text")])
    result = extract("# US-1 Large\n" + "\n".join("AC: x" for _ in range(100)))
    assert result.files[0]["status"] == "failed" and not result.observations
    row, = extract("# US-1 Title\nDescription: normal\n").observations
    with pytest.raises(ValueError, match="field"):
        replace(row, fields=(DocumentField("step", "bad", 0, 1),)).payload("a\nb\n", text_digest("a\nb\n"))


def test_unknown_section_cannot_be_misclassified_as_an_acceptance_criterion():
    row, = extract("# US-1 Header\n## Acceptance criteria\nAC-1: Required.\n## Notes\nNot an oracle.\n").observations
    assert [f.value for f in row.fields if f.name == "acceptance_criterion"] == ["AC-1: Required."]


def test_overlong_reference_list_and_inaccessible_field_are_reported_not_truncated():
    result = extract("# TC-1 Title\nReferences: " + " ".join(f"US-{index}" for index in range(101)), "test_asset")
    assert not result.observations and result.files[0]["status"] == "failed"


def test_titleless_requirement_header_and_python_test_script_are_evidenced_not_executed():
    row, = extract("# US-101\nAs a buyer, I can checkout.\n").observations
    assert row.kind == "requirement" and row.external_id == "US-101"
    assert "missing_acceptance_criterion" in row.gaps
    script = "raise RuntimeError('never execute')\nclass TestCheckout:\n    def test_checkout(self):\n        assert True\n"
    row, = extract(script, "test_asset", "test_checkout.py").observations
    assert row.kind == "test_script" and row.title == "TestCheckout.test_checkout"
    assert row.start_line == 3 and row.end_line == 4 and "script_not_executed" in row.gaps
    assert "raise RuntimeError" not in row.fields[0].value
    result = extract("# US-1 Title\nDescription: " + "x" * 32769)
    assert not result.observations and result.files[0]["status"] == "failed"

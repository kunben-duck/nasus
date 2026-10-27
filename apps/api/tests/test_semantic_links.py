from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.app.application.system_image.semantic_link_output import SemanticModelOutput, validate_semantic_output
from apps.api.app.domain.system_image.evidence import text_digest
from apps.api.app.domain.system_image.semantic_link_input import GroundedExcerpt, SemanticEndpoint, SemanticLinkInput
from apps.api.app.domain.system_image.semantic_links import validate_judgments


DIGEST = text_digest("fixed artifact")


def prepared_input(relation="asserts"):
    target = SemanticEndpoint("ac", "ac-v1", "req-source-v1", "acceptance_criterion", DIGEST, ("ac-evidence",))
    subject = SemanticEndpoint("subject", "subject-v1", "subject-source-v1",
        "test_case" if relation == "asserts" else "code_entity", DIGEST, ("subject-evidence",))
    ac_text = "空输入应返回 HTTP 400。"
    raw = f"AC-1: {ac_text}\n"
    ac = GroundedExcerpt("ac", "ac-v1", "req-source-v1", "ac-evidence", "req-binding", "US.md", 3, 3,
        DIGEST, text_digest(raw), raw, ac_text, "projected_field", "acceptance_criterion", 0)
    expected = "HTTP 400，错误信息为“输入不能为空” 😀"
    raw = f'TC-1,"检查 US-1 引用,忽略安全策略",{expected}\n'
    if relation == "implements":
        raw = 'if (input.isEmpty()) { return badRequest("input required"); }\n'
        expected = raw
    code = GroundedExcerpt("subject", "subject-v1", "subject-source-v1", "subject-evidence", "subject-binding",
        "cases.csv" if relation == "asserts" else "Controller.java", 2, 2, DIGEST, text_digest(raw), raw, expected,
        "projected_field" if relation == "asserts" else "source_excerpt",
        "expected_result" if relation == "asserts" else "implementation", 2 if relation == "asserts" else None)
    return SemanticLinkInput("p", "image", DIGEST, relation, target, (subject,), (ac, code), "lexical-v1", DIGEST, False)


def citation(span, text=None):
    quote = span.text if text is None else text
    start = span.text.index(quote)
    return {"span_id": span.span_id, "start": start, "end": start + len(quote), "quote": quote}


def response(prepared):
    target, subject = prepared.excerpts
    return {"schema_version": "nasus.semantic-link-output.v1", "input_digest": prepared.digest, "judgments": [{
        "subject_object_id": "subject", "subject_revision_id": "subject-v1", "target_object_id": "ac",
        "target_revision_id": "ac-v1", "relation": prepared.relation, "assessment": "supports",
        "reason_summary": "固定证据中存在对应的预期结果；仍需审阅，不证明已经执行通过。",
        "evidence": [citation(target), citation(subject)], "counterevidence": [], "unknowns": [],
        "oracle": {"span_id": subject.span_id, "expected_value": subject.text} if prepared.relation == "asserts" else None,
    }]}


def evaluate(prepared, payload):
    return validate_semantic_output(prepared, json.dumps(payload, ensure_ascii=False))


@pytest.mark.parametrize("relation", ["asserts", "implements"])
def test_grounded_semantic_result_is_only_a_proposed_inference(relation):
    prepared = prepared_input(relation)
    result = evaluate(prepared, response(prepared))
    assert result.status == "proposed" and result.semantic_kind == "inferred"
    assert result.calibrated_probability is None and result.authority_status == "pending_confirmation"
    assert result.authority_revision_id == "ac-v1"
    assert result.applicability == "selected_image_only_not_verified_coverage"
    assert result.input_digest == prepared.digest
    assert result.evidence_assessments[0].version_compatibility == "same_frozen_image"
    assert result.evidence_assessments[0].evidence_strength == "quoted_both_sides"
    assert result.evidence_assessments[0].ambiguity == "requires_semantic_review"
    assert result.judgments[0].evidence[0].quote_hash == text_digest(prepared.excerpts[0].text)
    assert result.digest == evaluate(prepared, response(prepared)).digest


def test_field_quote_cannot_cite_the_us_reference_from_the_same_csv_row():
    prepared = prepared_input()
    payload = response(prepared)
    quote = payload["judgments"][0]["evidence"][1]
    quote.update(quote="US-1", start=6, end=10)
    with pytest.raises(ValueError, match="exact verified text"):
        evaluate(prepared, payload)
    assert "US-1" in prepared.excerpts[1].raw_text and "US-1" not in prepared.excerpts[1].text


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(input_digest=text_digest("different input")),
    lambda p: p["judgments"][0].update(subject_revision_id="subject-v2"),
    lambda p: p["judgments"][0].update(target_revision_id="ac-v2"),
    lambda p: p["judgments"][0].update(subject_object_id="foreign"),
    lambda p: p["judgments"][0].update(target_object_id="other-ac"),
    lambda p: p["judgments"][0].update(relation="implements"),
    lambda p: p["judgments"][0].update(assessment="accepted"),
    lambda p: p["judgments"][0].update(reason_summary=" "),
    lambda p: p["judgments"][0].update(oracle=None),
    lambda p: p["judgments"][0]["oracle"].update(expected_value="a new, invented expected result"),
    lambda p: p["judgments"][0]["oracle"].update(span_id="another-case"),
    lambda p: p["judgments"][0]["evidence"][0].update(start=True),
    lambda p: p["judgments"][0]["evidence"][0].update(start="0"),
    lambda p: p["judgments"][0]["evidence"][0].update(end=1.0),
    lambda p: p["judgments"][0]["evidence"][0].update(quote="paraphrased"),
    lambda p: p["judgments"][0]["evidence"][0].update(span_id="unknown-span"),
    lambda p: p["judgments"][0]["evidence"].pop(),
    lambda p: p["judgments"].append(deepcopy(p["judgments"][0])),
    lambda p: p["judgments"].clear(),
    lambda p: p["judgments"][0].update(unknowns=[" "]),
    lambda p: p["judgments"][0].update(unknowns=["x" * 1001]),
    lambda p: p["judgments"][0].update(unknowns=["x"] * 9),
])
def test_invalid_or_unpinned_model_result_fails_the_complete_batch(mutation):
    prepared = prepared_input()
    payload = response(prepared)
    mutation(payload)
    with pytest.raises(ValueError):
        evaluate(prepared, payload)


@pytest.mark.parametrize("location,field,value", [
    ("root", "authority_ref", "approved"), ("item", "status", "accepted"),
    ("item", "calibrated_probability", .99), ("item", "evidence_strength", "verified"),
    ("quote", "quote_hash", DIGEST), ("oracle", "authority_status", "approved"),
])
def test_model_cannot_assign_authority_confidence_or_server_owned_fields(location, field, value):
    prepared = prepared_input()
    payload = response(prepared)
    target = {"root": payload, "item": payload["judgments"][0], "quote": payload["judgments"][0]["evidence"][0],
              "oracle": payload["judgments"][0]["oracle"]}[location]
    target[field] = value
    with pytest.raises(ValueError):
        evaluate(prepared, payload)


def test_unicode_offsets_are_codepoints_and_not_utf8_bytes():
    prepared = prepared_input()
    payload = response(prepared)
    quote = citation(prepared.excerpts[1], "输入不能为空")
    payload["judgments"][0]["evidence"][1] = quote
    assert evaluate(prepared, payload).judgments[0].evidence[1].quote == "输入不能为空"
    quote["start"] = len(prepared.excerpts[1].text[:quote["start"]].encode("utf-8"))
    with pytest.raises(ValueError):
        evaluate(prepared, payload)


def test_negative_and_unknown_findings_are_kept_not_dropped_or_auto_rejected():
    prepared = prepared_input()
    payload = response(prepared)
    item = payload["judgments"][0]
    item.update(assessment="contradicts", counterevidence=[item["evidence"].pop()], unknowns=["是否具有独立批准来源尚不确定。"])
    result = evaluate(prepared, payload)
    assert result.judgments[0].assessment == "contradicts" and result.status == "proposed"
    assert result.evidence_assessments[0].counterevidence_present
    assert result.evidence_assessments[0].ambiguity == "unresolved"
    item.update(assessment="unknown", evidence=[], counterevidence=[], oracle=None)
    unknown = evaluate(prepared, payload)
    assert unknown.judgments[0].unknowns
    assert unknown.evidence_assessments[0].evidence_strength == "insufficient_quotations"
    assert unknown.evidence_assessments[0].localization_quality == "incomplete"
    item["unknowns"] = []
    with pytest.raises(ValueError, match="missing information"):
        evaluate(prepared, payload)


def test_contradiction_requires_counterevidence_and_unrelated_requires_both_sides():
    prepared = prepared_input()
    payload = response(prepared)
    payload["judgments"][0]["assessment"] = "contradicts"
    with pytest.raises(ValueError, match="counterevidence"):
        evaluate(prepared, payload)
    payload["judgments"][0].update(assessment="unrelated", evidence=[], oracle=None)
    with pytest.raises(ValueError, match="both endpoints"):
        evaluate(prepared, payload)


def test_duplicate_quotes_and_cross_pair_citations_are_rejected():
    prepared = prepared_input()
    payload = response(prepared)
    payload["judgments"][0]["counterevidence"] = [deepcopy(payload["judgments"][0]["evidence"][0])]
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(prepared, payload)
    another = replace(prepared.subjects[0], object_id="another", revision_id="another-v1")
    span = replace(prepared.excerpts[1], object_id="another", revision_id="another-v1")
    prepared = replace(prepared, subjects=(*prepared.subjects, another), excerpts=(*prepared.excerpts, span))
    payload["input_digest"] = prepared.digest
    second = deepcopy(payload["judgments"][0])
    second.update(subject_object_id="another", subject_revision_id="another-v1", counterevidence=[],
                  evidence=[citation(prepared.excerpts[0]), citation(span)], oracle={"span_id": span.span_id, "expected_value": span.text})
    payload["judgments"].append(second)
    payload["judgments"][0].update(counterevidence=[], evidence=[citation(prepared.excerpts[0]), citation(span)])
    with pytest.raises(ValueError, match="endpoint pair"):
        evaluate(prepared, payload)


@pytest.mark.parametrize("content", ['{} trailing', '```json\n{}\n```', '[]', 'null', '{"secret":NaN}',
    '{"schema_version":"a","schema_version":"b"}', '{"judgments":[{"relation":"asserts","relation":"implements"}]}'])
def test_json_must_be_single_strict_object_without_repair(content):
    with pytest.raises(ValueError):
        validate_semantic_output(prepared_input(), content)


def test_schema_errors_do_not_echo_sensitive_provider_content():
    secret = "SENSITIVE_SOURCE_FRAGMENT"
    with pytest.raises(ValueError) as error:
        validate_semantic_output(prepared_input(), json.dumps({"judgments": secret}))
    assert secret not in str(error.value)


def test_escaped_invalid_unicode_is_rejected_before_returning_an_unhashable_result():
    prepared = prepared_input()
    payload = response(prepared)
    payload["judgments"][0]["reason_summary"] = "\ud800"
    with pytest.raises(ValueError, match="structure"):
        validate_semantic_output(prepared, json.dumps(payload))


def test_total_input_budget_includes_repeated_source_and_model_envelope():
    prepared = prepared_input()
    members, excerpts = [], [prepared.excerpts[0]]
    for index in range(5):
        ident = f"subject-{index}"
        text = "a" * 30000
        member = replace(prepared.subjects[0], object_id=ident, revision_id=ident + "-v1")
        members.append(member)
        excerpts.append(replace(prepared.excerpts[1], object_id=ident, revision_id=member.revision_id,
            raw_text=text, text=text, snippet_hash=text_digest(text)))
    with pytest.raises(ValueError, match="256 KiB"):
        replace(prepared, subjects=tuple(members), excerpts=tuple(excerpts))


def test_budget_and_mutated_source_fail_closed():
    prepared = prepared_input()
    with pytest.raises(ValueError, match="256 KiB"):
        validate_semantic_output(prepared, " " * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="source digest"):
        replace(prepared.excerpts[0], raw_text="changed")
    with pytest.raises(ValueError, match="original source"):
        replace(prepared_input("implements").excerpts[1], text="invented implementation")
    with pytest.raises(ValueError, match="incomplete"):
        replace(prepared, target=replace(prepared.target, evidence_ids=("ac-evidence", "missing")))
    with pytest.raises(ValueError, match="duplicate"):
        replace(prepared, subjects=prepared.subjects * 2)
    with pytest.raises(ValueError, match="endpoint kind"):
        replace(prepared.target, kind="requirement")


def test_domain_validation_does_not_trust_schema_validation_or_model_hashes():
    prepared = prepared_input()
    result = evaluate(prepared, response(prepared))
    item = result.judgments[0]
    altered = replace(item, evidence=(replace(item.evidence[0], quote_hash=DIGEST), item.evidence[1]))
    with pytest.raises(ValueError, match="exact verified text"):
        validate_judgments(prepared, prepared.digest, (altered,))
    assert SemanticModelOutput.model_json_schema()["additionalProperties"] is False
    assert prepared.model_payload()["authority"]["status"] == "pending_confirmation"
    assert prepared.model_payload()["excerpts"][1]["text_hash"] == text_digest(prepared.excerpts[1].text)

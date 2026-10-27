from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.context_retrieval_inputs import ContextRetrievalInputs, ContextRetrievalSelection
from apps.api.app.application.system_image.publication_read_models import PublishedImagePin
from apps.api.app.domain.system_image.context_retrieval_plan import ContextRetrievalQuery, source_query, query_plan_budget
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge


def query(ident="ac", text="source AC"):
    return ContextRetrievalQuery(ident, "revision", "parent", "parent-revision", "source", "binding", ((ident, "evidence"),), text)


def test_queries_budget_utf8_without_truncation_and_exact_batch_counts():
    assert source_query(("Empty input returns 400",), ("Search",)) == "Requirement description:\nSearch\n\nAcceptance criterion:\nEmpty input returns 400"
    assert query_plan_budget(()) == {**query_plan_budget(()), "query_count": 0, "max_model_calls": 0, "input_bytes": 0}
    for count in (1, 32, 33, 256):
        queries = tuple(query(f"ac-{index:03}", "\u4e2d\u6587") for index in range(count))
        budget = query_plan_budget(queries)
        assert budget["max_model_calls"] == (count + 31) // 32
        assert budget["input_bytes"] == count * 6 and budget["max_query_bytes"] == 6
    with pytest.raises(ImageRevisionPageTooLarge):
        source_query(("\u4e2d" * 1400,), ())
    with pytest.raises(ImageRevisionPageTooLarge):
        query_plan_budget(tuple(query(f"ac-{index:03}") for index in range(257)))
    for invalid in ((query("z"), query("a")), (query(), query()), (replace(query(), evidence_selections=()),)):
        with pytest.raises(ImageRevisionIntegrityError):
            query_plan_budget(invalid)
    assert query_plan_budget((query(),))["queries_digest"] != query_plan_budget((replace(query(), parent_revision_id="new"),))["queries_digest"]


@pytest.fixture
def inputs():
    pin = PublishedImagePin(publication_id="pub", baseline_id="base", image_revision_id="image",
        image_artifact_hash="sha256:" + "a" * 64, manifest_id="manifest", manifest_hash="sha256:" + "b" * 64, sequence=1)
    selection = ContextRetrievalSelection(project_id="project", publication_id="pub", generation_id="index")
    members, objects, documents, index_docs = [], [], {}, []
    for ident, kind, fields in (("parent", "requirement", [("description", "Shared description"), ("acceptance_criterion", "Sibling must never leak")]),
            ("ac-1", "acceptance_criterion", [("acceptance_criterion", "First independent AC")]),
            ("ac-2", "acceptance_criterion", [("acceptance_criterion", "Second independent AC")])):
        evidence, values = [], []
        for line, (name, value) in enumerate(fields, 1):
            proof = {"evidence_id": f"{ident}-{line}", "start_line": line, "end_line": line, "snippet_hash": f"hash-{ident}-{line}"}
            evidence.append(proof)
            values.append({"name": name, "value": value, **{key: proof[key] for key in ("start_line", "end_line", "snippet_hash")}})
            index_docs.append({"document": {"object_id": ident, "evidence_id": proof["evidence_id"], "revision_id": ident + "-revision",
                "source_revision_id": "source", "binding_id": "binding", "kind": "source_document"}})
        members.append({"object_id": ident, "document_revision_id": ident + "-revision", "source_revision_id": "source",
            "kind": "source_document", "evidence_ids": [item["evidence_id"] for item in evidence]})
        objects.append({"id": ident, "type": "Requirement" if kind == "requirement" else "SourceAcceptanceCriterion"})
        documents[ident] = {"document": {"parent_document_revision_id": "parent-revision" if kind != "requirement" else None},
            "projection": {"kind": kind}, "fields": values, "evidence": evidence, "next_offset": None}
    payload = {"objects": objects, "members": members, "source_members": [{"source_revision_id": "source", "binding_id": "binding"}]}
    reads, verified = [], []
    def read(project, image, ident, **kwargs):
        reads.append((ident, kwargs["offset"]))
        return deepcopy(documents[ident])
    images = SimpleNamespace(verified_read_session=nullcontext,
        frozen_snapshot=lambda *args: (SimpleNamespace(artifact_hash=pin.image_artifact_hash, manifest_id=pin.manifest_id, manifest_hash=pin.manifest_hash), payload),
        read_document=read, verify_evidence_selection=lambda project, image, proofs: verified.extend(proofs))
    index = {"model": {"config_digest": "model-digest"}, "documents": index_docs}
    return SimpleNamespace(images=images, selection=selection, pin=pin, payload=payload, documents=documents, index=index,
        prepare=lambda: ContextRetrievalInputs(images).prepare(selection, pin, index, "index-hash"), reads=reads, verified=verified)


def test_all_ac_queries_share_cached_parent_but_never_siblings_or_oracles(inputs):
    v = inputs
    queries, preview = v.prepare()
    assert len(queries) == 2 and [item.target_object_id for item in queries] == ["ac-1", "ac-2"]
    assert "First independent" in queries[0].text and "Second independent" not in queries[0].text
    assert all("Sibling" not in query.text and "Shared description" in query.text for query in queries)
    assert v.reads.count(("parent", 0)) == 1
    assert set(v.verified) == {("ac-1", "ac-1-1"), ("ac-2", "ac-2-1"), ("parent", "parent-1")}
    assert preview["state"] == "prepared" and preview["query_count"] == 2 and preview["max_model_calls"] == 1
    assert preview["execution_available"] is True and preview["model_calls_made"] == 0
    assert "independent" not in str(preview) and "Shared description" not in str(preview)
    assert v.prepare()[1] == preview
    v.payload["objects"][0]["approved_oracle"] = "Mutable business approval must not enter this query"
    assert v.prepare()[1] == preview
    v.index["model"]["config_digest"] = "changed"
    assert v.prepare()[1]["plan_digest"] != preview["plan_digest"]


@pytest.mark.parametrize("corruption", ["parent", "parent_kind", "source", "field_evidence", "index_evidence", "index_revision", "index_binding", "no_ac_fields"])
def test_query_input_fails_closed_on_missing_frozen_or_consented_evidence(inputs, corruption):
    v = inputs
    if corruption == "parent":
        v.documents["ac-1"]["document"]["parent_document_revision_id"] = "missing"
    elif corruption == "parent_kind":
        v.documents["parent"]["projection"]["kind"] = "test_case"
    elif corruption == "source":
        v.payload["members"][0]["source_revision_id"] = "another-source"
    elif corruption == "field_evidence":
        v.documents["ac-1"]["fields"][0]["snippet_hash"] = "wrong"
    elif corruption == "index_evidence":
        v.index["documents"] = [item for item in v.index["documents"] if item["document"]["object_id"] != "ac-1"]
    elif corruption.startswith("index_"):
        v.index["documents"][0]["document"]["revision_id" if corruption == "index_revision" else "binding_id"] = "wrong"
    else:
        v.documents["ac-1"]["fields"] = []
    with pytest.raises(ImageRevisionIntegrityError):
        v.prepare()


def test_no_requirements_does_not_fabricate_queries_and_oversized_ac_is_not_dropped(inputs):
    v = inputs
    v.documents["ac-1"]["fields"][0]["value"] = "x" * 4096
    with pytest.raises(ImageRevisionPageTooLarge):
        v.prepare()
    v.payload["objects"] = []
    queries, preview = v.prepare()
    assert queries == () and preview["state"] == "missing_requirements" and preview["max_model_calls"] == 0


def test_query_reads_all_document_pages_and_rejects_nonadvancing_cursor(inputs):
    v = inputs
    original = v.images.read_document
    def paginated(project, image, ident, *, offset, **kwargs):
        page = original(project, image, ident, offset=offset)
        if ident == "parent":
            page["fields"] = page["fields"][offset:offset + 1]
            page["next_offset"] = 1 if offset == 0 else None
        return page
    v.images.read_document = paginated
    queries, _ = v.prepare()
    assert "Shared description" in queries[0].text and ("parent", 1) in v.reads
    v.documents["ac-1"]["next_offset"] = 0
    with pytest.raises(ImageRevisionIntegrityError, match="cursor"):
        v.prepare()


def test_query_budget_refuses_to_omit_constraints_even_when_only_one_is_an_ac(inputs):
    v = inputs
    v.payload["objects"].extend({"id": f"rule-{i}", "type": "SourceBusinessRule"} for i in range(256))
    with pytest.raises(ImageRevisionPageTooLarge, match="no AC was omitted"):
        v.prepare()
    assert not v.reads

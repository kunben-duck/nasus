"""Synthetic, in-memory frozen specs only; no database, uploads or services."""
from dataclasses import asdict, replace
import json
import socket

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.domain.system_image.document_components import requirement_components
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor
from apps.api.app.infrastructure.system_image import openapi_document_extractor as projection
from apps.api.app.infrastructure.system_image import openapi_document_parser as syntax


YAML_SPEC = """openapi: 3.0.3
info:
  title: Synthetic articles
  version: '1'
paths:
  /articles:
    get:
      summary: List articles
      parameters:
        - name: limit
          in: query
          required: false
          schema:
            type: integer
      responses:
        '200':
          description: A documented response, not an approved oracle
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Articles'
components:
  schemas:
    Articles:
      type: object
      required: [articles]
      properties:
        articles:
          type: array
          items:
            type: string
"""


def unit(text, path="api/openapi.yml"):
    return SourceTextUnit(path, text, len(text.encode("utf-8")), text_digest(text))


def extract(text=YAML_SPEC, *, path="api/openapi.yml", source_type="us_doc"):
    return ExplicitDocumentExtractor().extract(source_type, [unit(text, path)])


def minimal(**updates):
    return {"openapi": "3.1.0", "info": {"title": "Synthetic", "version": "1"},
            "paths": {"/articles": {"get": {"responses": {"200": {"description": "OK"}}}}}, **updates}


def operation(result):
    return next(row for row in result.observations if row.title.startswith("OpenAPI GET"))


def values(row):
    return [json.loads(field.value) for field in row.fields]


def assert_failed(result, reason):
    assert result.observations == ()
    assert result.files == ({"path": "api/openapi.yml", "status": "failed", "reason": reason,
                             "extractor_version": "nasus.openapi-document.v1"},)


@pytest.mark.parametrize("source_type,kind", [("us_doc", "requirement_document"), ("test_asset", "test_document")])
def test_yaml_provides_supporting_context_never_ac_components_or_oracle(source_type, kind):
    result = extract(source_type=source_type)
    assert result.files[0]["status"] == "parsed"
    assert result.files[0]["entity_count"] == 3
    row = operation(result)
    assert row.title == "OpenAPI GET /articles"
    assert values(row)[0] == {"basis": "supporting_specification_not_approved", "method": "GET", "path": "/articles"}
    assert values(row)[1] == {"parameter": "limit", "in": "query", "required": False, "schema": {"type": "integer"}}
    assert values(row)[2] == {"response_status": "200", "content": [
        {"media_type": "application/json", "schema": {"$ref": "not_expanded"}}]}
    schema = next(item for item in result.observations if item.title == "OpenAPI schema Articles")
    assert values(schema)[0]["schema"]["required"] == ["articles"]
    for row in result.observations:
        assert row.kind == kind and row.external_id is None and row.references == ()
        assert row.identity_status == "source_occurrence"
        assert all(field.name == "description" for field in row.fields)
        assert requirement_components(row) == ()
        assert {"supporting_specification_not_approved", "independent_oracle_review_required"} <= set(row.gaps)
        payload = row.payload(YAML_SPEC, text_digest(YAML_SPEC))
        assert payload["semantic_status"] == "source_projection_not_approved_specification"
        assert payload["reference_semantics"] == "references_only_not_asserts_or_implements"
        assert "approved" not in payload and "oracle" not in payload


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_yaml_provenance_uses_original_lines_and_hashes_not_reserialized_values(newline):
    text = YAML_SPEC.replace("\n", newline)
    result = extract(text)
    row = operation(result)
    payload = row.payload(text, text_digest(text))
    assert payload["locator"] == {"relative_path": "api/openapi.yml", "start_line": 6, "end_line": 21, "precision": "exact"}
    lines = source_lines(text)
    assert payload["source_file_hash"] == text_digest(text)
    for row in result.observations:
        payload = row.payload(text, text_digest(text))
        assert payload["snippet_hash"] == text_digest("".join(lines[row.start_line - 1:row.end_line]))
        for field in payload["fields"]:
            assert field["snippet_hash"] == text_digest("".join(lines[field["start_line"] - 1:field["end_line"]]))
    assert payload["source_file_hash"] != text_digest(text + " ")


@pytest.mark.parametrize("indent", [None, 2])
def test_strict_json_and_repeated_reads_have_deterministic_provenance(indent):
    data = minimal()
    data["paths"]["/articles"]["post"] = {"requestBody": {"content": {"application/json": {
        "schema": {"type": "object", "properties": {"article": {"type": "string"}}}}}},
        "responses": {"201": {"description": "Created"}}}
    text = json.dumps(data, indent=indent)
    first = extract(text, path="api/openapi.json")
    assert first == extract(text, path="api/openapi.json")
    assert first.files[0]["entity_count"] == 3
    for row in first.observations:
        payload = row.payload(text, text_digest(text))
        assert payload == row.payload(text, text_digest(text))
        assert payload["snippet_hash"] == text_digest("".join(source_lines(text)[row.start_line - 1:row.end_line]))
        if indent is None:
            assert row.start_line == row.end_line == 1
    post = next(row for row in first.observations if row.title == "OpenAPI POST /articles")
    assert values(post)[1]["content"][0]["schema"]["properties"] == [{"name": "article", "schema": {"type": "string"}}]


@pytest.mark.parametrize("reference,gap", [
    ("#/components/schemas/Item", "openapi_local_reference_not_expanded"),
    ("#/components/schemas/a~1b~0c", "openapi_local_reference_not_expanded"),
    ("#", "openapi_local_reference_not_expanded"),
    ("#/components/schemas/Missing", "openapi_unresolved_local_reference"),
    ("#/components/schemas/bad~2escape", "openapi_malformed_reference"),
    ("#anchor", "openapi_malformed_reference"),
    ("#/%70aths", "openapi_malformed_reference"),
    ("", "openapi_malformed_reference"),
    (42, "openapi_malformed_reference"),
    (1e100, "openapi_malformed_reference"),
    (None, "openapi_malformed_reference"),
    (True, "openapi_malformed_reference"),
    ({"expression": "dynamic"}, "openapi_malformed_reference"),
    ("https://user:do-not-leak@invalid.example/schema?token=do-not-leak", "openapi_external_reference_not_fetched"),
    ("file:///private/do-not-leak", "openapi_external_reference_not_fetched"),
    ("../../do-not-leak.json", "openapi_external_reference_not_fetched"),
    ("https://${SECRET}/schema", "openapi_dynamic_references_not_supported"),
])
def test_references_are_bounded_gaps_never_fetched_or_turned_into_requirement_edges(reference, gap, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("reference attempted network or file I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    data = minimal(components={"schemas": {"Item": {"$ref": reference}, "a/b~c": {"type": "string"}}})
    result = extract(json.dumps(data))
    assert result.files[0]["status"] == "parsed"
    assert gap in result.files[0]["gaps"]
    assert all(gap in row.gaps for row in result.observations)
    assert all(row.references == () for row in result.observations)
    assert "do-not-leak" not in json.dumps(asdict(result))


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef", "$id", "$dynamicAnchor", "$anchor"])
def test_dynamic_reference_scope_is_not_resolved(keyword):
    data = minimal(components={"schemas": {"Item": {keyword: "do-not-leak", "$ref": "#"}}})
    result = extract(json.dumps(data))
    assert "openapi_dynamic_references_not_supported" in result.files[0]["gaps"]
    assert "do-not-leak" not in json.dumps(asdict(result))


@pytest.mark.parametrize("schema_type", [None, True, 12])
def test_non_string_schema_types_cannot_be_promoted_to_type_claims(schema_type):
    result = extract(json.dumps(minimal(components={"schemas": {"Item": {"type": schema_type}}})))
    row = next(row for row in result.observations if row.title == "OpenAPI schema Item")
    assert values(row)[0]["schema"] == {}
    assert "openapi_schema_form_not_supported" in row.gaps


def test_recursive_local_refs_and_path_item_refs_remain_visible_unexpanded_gaps():
    data = minimal(paths={"/articles": {"$ref": "#/paths/~1articles"}},
                   components={"schemas": {"Item": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Item"}}}}})
    result = extract(json.dumps(data))
    assert len(result.observations) == 2
    assert result.files[0]["status"] == "parsed"
    assert "openapi_local_reference_not_expanded" in result.files[0]["gaps"]


def test_ui_projection_omits_prose_credentials_values_urls_and_parser_messages():
    secret = "do-not-leak-credential-123"
    schema = {"type": "string", "example": secret, "default": secret, "enum": [secret], "const": secret,
              "description": secret, "title": secret, "pattern": secret}
    data = minimal(info={"title": secret, "version": secret}, servers=[{"url": "https://user:" + secret + "@example.invalid"}],
        components={"schemas": {"Credentials": {"type": "object", "properties": {"password": schema, "token": schema}}}})
    op = data["paths"]["/articles"]["get"]
    op.update(summary=secret, description=secret, operationId=secret,
              parameters=[{"in": "header", "name": "Authorization", "example": secret, "schema": schema}])
    op["responses"]["200"].update(description=secret, headers={"Set-Cookie": {"example": secret}},
                                content={"application/json": {"example": {"token": secret}, "schema": schema}})
    result = extract(json.dumps(data))
    serialized = json.dumps(asdict(result))
    assert secret not in serialized and "https://" not in serialized
    assert "Authorization" in serialized and "password" in serialized
    data["paths"] = {"/articles?token=" + secret: {"get": op}}
    result = extract(json.dumps(data))
    assert operation(result).title == "OpenAPI GET [omitted]"
    assert secret not in json.dumps(asdict(result))
    result = extract(YAML_SPEC + "broken: [" + secret)
    assert_failed(result, "invalid_openapi_structure")
    assert secret not in json.dumps(asdict(result))


@pytest.mark.parametrize("payload,reason", [
    ("!!python/object/apply:os.system ['touch SHOULD_NOT_EXIST']", "openapi_yaml_tags_not_supported"),
    ("!!python/name:builtins.eval ''", "openapi_yaml_tags_not_supported"),
    ("!include /etc/passwd", "openapi_yaml_tags_not_supported"),
    ("&loop [*loop]", "openapi_yaml_aliases_not_supported"),
    ("&a [x, x]\nb: &b [*a, *a]\nc: [*b, *b]", "openapi_yaml_aliases_not_supported"),
    ("{<<: {type: string}}", "openapi_ambiguous_mapping"),
])
def test_malicious_yaml_never_constructs_or_executes(payload, reason, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("YAML attempted a constructor or execution")

    monkeypatch.setattr("os.system", forbidden)
    monkeypatch.setattr(yaml_constructor(), "construct_object", forbidden)
    assert_failed(extract(YAML_SPEC + "unsafe: " + payload + "\n"), reason)


def yaml_constructor():
    from yaml.constructor import BaseConstructor
    return BaseConstructor


@pytest.mark.parametrize("text,reason", [
    (YAML_SPEC + "openapi: 3.1.0\n", "openapi_ambiguous_mapping"),
    (YAML_SPEC + "---\nopenapi: 3.1.0\n", "openapi_multiple_documents_not_supported"),
    ("openapi: [", "invalid_openapi_structure"),
    ("a: b", "not_an_openapi_document"),
    ("swagger: '2.0'", "not_an_openapi_document"),
    (YAML_SPEC.replace("3.0.3", "4.0.0"), "openapi_version_not_supported"),
    (YAML_SPEC.replace("    get:\n", "    get: not-an-operation\n    ignored:\n"), "invalid_openapi_operation"),
])
def test_malformed_or_unhandled_documents_are_explicit_failures(text, reason):
    assert_failed(extract(text), reason)


@pytest.mark.parametrize("text", [YAML_SPEC, '{"openapi": "3.0.3",}', '{"openapi": NaN}', '{"openapi": "3.0.3", "openapi": "3.1.0"}'])
def test_json_extension_does_not_accept_yaml_or_ambiguous_json(text):
    result = extract(text, path="api/openapi.json")
    assert not result.observations and result.files[0]["status"] == "failed"


@pytest.mark.parametrize("module,constant,limit,reason", [
    (syntax, "MAX_BYTES", 32, "openapi_byte_limit"),
    (syntax, "MAX_DEPTH", 4, "openapi_depth_limit"),
    (syntax, "MAX_NODES", 10, "openapi_node_limit"),
    (syntax, "MAX_SCALAR", 4, "openapi_scalar_limit"),
    (syntax, "MAX_REFERENCES", 0, "openapi_reference_limit"),
    (projection, "MAX_OPERATIONS", 0, "openapi_operation_limit"),
    (projection, "MAX_SCHEMAS", 0, "openapi_schema_limit"),
    (projection, "MAX_FIELDS", 1, "openapi_field_limit"),
])
def test_limits_fail_closed_without_partial_success(module, constant, limit, reason, monkeypatch):
    monkeypatch.setattr(module, constant, limit)
    assert_failed(extract(), reason)


def test_actual_depth_and_size_bombs_are_bounded():
    assert_failed(extract(YAML_SPEC + "unsafe: " + "[" * 10000 + "0" + "]" * 10000), "openapi_depth_limit")
    assert_failed(extract(" " * (syntax.MAX_BYTES + 1)), "openapi_byte_limit")


def test_schema_projection_and_serialized_field_limits_are_explicit():
    schema = {"type": "string"}
    for _ in range(projection.MAX_SCHEMA_DEPTH + 2):
        schema = {"type": "array", "items": schema}
    assert_failed(extract(json.dumps(minimal(components={"schemas": {"Item": schema}}))),
                  "openapi_schema_projection_depth_limit")
    schema = {"type": "object", "properties": {f"field_{i}": {"type": "string"} for i in range(1000)}}
    assert_failed(extract(json.dumps(minimal(components={"schemas": {"Item": schema}}))), "openapi_field_size_limit")


def test_source_locator_offsets_follow_lf_even_when_yaml_counts_other_line_breaks():
    text = YAML_SPEC.replace("Synthetic articles", '"Synthetic\u0085articles\u2028note"')
    row = operation(extract(text))
    assert row.start_line == 6 and row.end_line == 21
    assert row.fields[0].start_line == 6
    payload = row.payload(text, text_digest(text))
    assert payload["fields"][0]["snippet_hash"] == text_digest("".join(source_lines(text)[5:21]))


@pytest.mark.parametrize("label", ["sk_shortSecret", "ghp_shortSecret", "AKIA" + "ABCDEFGHIJKLMNOP", "a" * 32])
def test_token_like_labels_are_not_copied_into_ui_fields_or_titles(label):
    result = extract(json.dumps(minimal(paths={"/" + label: {"get": {"responses": {"200": {"description": "OK"}}}}})))
    assert label not in json.dumps(asdict(result))
    assert operation(result).title == "OpenAPI GET [omitted]"


def test_archived_projection_contract_preserves_original_fingerprints_without_ac_children():
    from types import SimpleNamespace

    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
    from apps.api.app.infrastructure.system_image.archived_document_projection import ArchivedDocumentProjection

    source_unit = unit(YAML_SPEC)
    manifest = {"files": [{"path": source_unit.relative_path, "content_hash": source_unit.content_hash,
                           "byte_count": source_unit.byte_count}]}
    source = SimpleNamespace(project_id="synthetic-project", id="synthetic-source", content_ref="memory:frozen",
                             content_hash=snapshot_digest(manifest))
    saved = []

    class Archive:
        def owns_ref(self, ref):
            return ref == "memory:frozen"

        def read_manifest(self, ref, **kwargs):
            assert ref == source.content_ref and kwargs["content_hash"] == source.content_hash
            return manifest

    class Artifacts:
        def put(self, project_id, payload):
            assert project_id == source.project_id
            saved.append(payload)
            digest = snapshot_digest(payload)
            return "memory:" + digest, digest

    class Repository:
        def record(self, source, items, **kwargs):
            assert kwargs["summary"]["parsed"] == 1
            assert kwargs["summary"]["entity_count"] == 3
            return tuple(items)

    adapter = ArchivedDocumentProjection(Archive(), Artifacts(), Repository())
    result = extract()
    first = adapter.record(source, result, [source_unit], captured_at="synthetic-time")
    assert first == adapter.record(source, extract(), [source_unit], captured_at="synthetic-time")
    assert len(first) == 3
    for identity, payload, ref, digest in first:
        assert identity["identity_status"] == "source_occurrence"
        assert payload["kind"] == "requirement_document"
        assert payload["extractor_version"] == "nasus.openapi-document.v1"
        assert payload["source_file_hash"] == source_unit.content_hash
        assert payload["source_manifest_hash"] == snapshot_digest(manifest)
        assert payload["semantic_status"] == "source_projection_not_approved_specification"
        assert "parent" not in payload
        assert digest == snapshot_digest(payload)
    report = saved[-1]
    assert report["schema"] == "nasus.source-document-extraction.v1"
    assert report["extractor_version"] == "nasus.explicit-document.v2"
    assert report["extractor_versions"] == ["nasus.openapi-document.v1"]
    assert "openapi_local_reference_not_expanded" in report["files"][0]["gaps"]
    assert report["payload_hashes"] == sorted(item[3] for item in first)
    with pytest.raises(ValueError, match="fingerprint"):
        adapter.record(source, result, [replace(source_unit, text=YAML_SPEC + " ")], captured_at="synthetic-time")


def test_other_sources_and_lossy_text_are_coverage_gaps_and_neighbors_survive_failure():
    for path in ("examples/errors.hurl", "official/articles.test.ts", "official/articles.test.js"):
        result = extract("throw new Error('do not execute')", path=path, source_type="test_asset")
        assert result.observations == ()
        assert result.files[0]["status"] == "unsupported"
        assert result.files[0]["reason"] == "exact_source_locator_adapter_required"
    result = ExplicitDocumentExtractor().extract("us_doc", [replace(unit(YAML_SPEC), text_is_lossless=False)])
    assert result.files[0]["status"] == "unsupported"
    result = ExplicitDocumentExtractor().extract("us_doc", [unit("broken: [", "bad.yml"), unit(YAML_SPEC)])
    assert [file["status"] for file in result.files] == ["failed", "parsed"]
    assert len(result.observations) == 3

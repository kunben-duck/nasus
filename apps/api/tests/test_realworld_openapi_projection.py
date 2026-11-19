"""Stripped RealWorld article/auth shapes; never read or recapture retained data.

Adapted from specs/api/openapi.yml at 25588846c314b15a5e427ffe816e6b4af7be68c7.
Original blob SHA-256: c5d1cfc6fad0d4c93d3294248e6521849255e17c084e5673204228154e80939b.
This smaller fixture uses its own lines/hash and synthetic credential markers;
it must not be presented as the original frozen source or approved authority.
"""
import json

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.domain.system_image.document_components import requirement_components
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor


ARTICLE_AUTH_SPEC = """openapi: 3.1.0
info: {title: Stripped RealWorld article/auth fixture, version: 2.0.0}
paths:
  /users/login:
    post:
      requestBody:
        $ref: '#/components/requestBodies/LoginUserRequest'
      responses:
        '200': {$ref: '#/components/responses/UserResponse'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '422': {$ref: '#/components/responses/GenericError'}
      x-codegen-request-body-name: body
  /articles:
    get:
      description: Authentication is optional; not an approved oracle.
      parameters:
        - {name: tag, in: query, schema: {type: string}}
        - {$ref: '#/components/parameters/offsetParam'}
        - {$ref: '#/components/parameters/limitParam'}
      responses:
        '200': {$ref: '#/components/responses/MultipleArticlesResponse'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '422': {$ref: '#/components/responses/GenericError'}
    post:
      requestBody:
        $ref: '#/components/requestBodies/NewArticleRequest'
      responses:
        '201': {$ref: '#/components/responses/SingleArticleResponse'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/ConflictError'}
        '422': {$ref: '#/components/responses/GenericError'}
      security: [{Token: []}]
      x-codegen-request-body-name: article
  /articles/{slug}:
    get:
      parameters:
        - {name: slug, in: path, required: true, schema: {type: string}}
      responses:
        '200': {$ref: '#/components/responses/SingleArticleResponse'}
        '404': {$ref: '#/components/responses/NotFound'}
        '422': {$ref: '#/components/responses/GenericError'}
    put:
      parameters:
        - {name: slug, in: path, required: true, schema: {type: string}}
      requestBody:
        $ref: '#/components/requestBodies/UpdateArticleRequest'
      responses:
        '200': {$ref: '#/components/responses/SingleArticleResponse'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '403': {$ref: '#/components/responses/Forbidden'}
        '404': {$ref: '#/components/responses/NotFound'}
        '422': {$ref: '#/components/responses/GenericError'}
      security: [{Token: []}]
    delete:
      parameters:
        - {name: slug, in: path, required: true, schema: {type: string}}
      responses:
        '204': {$ref: '#/components/responses/EmptyOkResponse'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '403': {$ref: '#/components/responses/Forbidden'}
        '404': {$ref: '#/components/responses/NotFound'}
        '422': {$ref: '#/components/responses/GenericError'}
      security: [{Token: []}]
components:
  schemas:
    LoginUser:
      required: [email, password]
      type: object
      properties:
        email: {type: string, format: email}
        password: {type: string, format: password, example: FIXTURE_ONLY_PASSWORD}
    User:
      required: [bio, email, image, token, username]
      type: object
      properties:
        email: {type: string, format: email}
        token: {type: string, example: FIXTURE_ONLY_TOKEN}
        username: {type: string}
        bio: {type: [string, 'null']}
        image: {type: [string, 'null']}
    Profile:
      required: [bio, following, image, username]
      type: object
      properties:
        username: {type: string}
        bio: {type: [string, 'null']}
        image: {type: [string, 'null']}
        following: {type: boolean}
    Article:
      required: [author, body, createdAt, description, favorited, favoritesCount, slug, tagList, title, updatedAt]
      type: object
      properties:
        slug: {type: string}
        title: {type: string}
        description: {type: string}
        body: {type: string}
        tagList: {type: array, items: {type: string}}
        createdAt: {type: string, format: date-time}
        updatedAt: {type: string, format: date-time}
        favorited: {type: boolean}
        favoritesCount: {type: integer}
        author: {$ref: '#/components/schemas/Profile'}
    NewArticle:
      required: [body, description, title]
      type: object
      properties:
        title: {type: string}
        description: {type: string}
        body: {type: string}
        tagList: {type: array, items: {type: string}}
    UpdateArticle:
      type: object
      properties:
        title: {type: string}
        description: {type: string}
        body: {type: string}
        tagList: {type: array, items: {type: string}}
    GenericErrorModel:
      required: [errors]
      type: object
      properties:
        errors: {type: object, additionalProperties: {type: array, items: {type: string}}}
  responses:
    SingleArticleResponse:
      description: Single article
      content:
        application/json:
          schema: {type: object, required: [article], properties: {article: {$ref: '#/components/schemas/Article'}}}
    MultipleArticlesResponse: {description: Wrapper intentionally omitted in this stripped fixture}
    UserResponse:
      description: User
      content:
        application/json:
          schema: {type: object, required: [user], properties: {user: {$ref: '#/components/schemas/User'}}}
    EmptyOkResponse: {description: No content, content: {}}
    Unauthorized: {description: Unauthorized}
    Forbidden: {description: Forbidden}
    NotFound: {description: Not found}
    ConflictError: {description: Conflict}
    GenericError: {description: Unexpected error}
  requestBodies:
    LoginUserRequest:
      required: true
      content:
        application/json:
          schema: {type: object, required: [user], properties: {user: {$ref: '#/components/schemas/LoginUser'}}}
    NewArticleRequest:
      required: true
      content:
        application/json:
          schema: {type: object, required: [article], properties: {article: {$ref: '#/components/schemas/NewArticle'}}}
    UpdateArticleRequest:
      required: true
      content:
        application/json:
          schema: {type: object, required: [article], properties: {article: {$ref: '#/components/schemas/UpdateArticle'}}}
  parameters:
    offsetParam: {in: query, name: offset, required: false, schema: {type: integer, minimum: 0}}
    limitParam: {in: query, name: limit, required: false, schema: {type: integer, minimum: 1, default: 20}}
  securitySchemes:
    Token: {type: apiKey, name: Authorization, in: header, description: FIXTURE_ONLY_AUTH_PROSE}
"""


def project(source_type="us_doc", text=ARTICLE_AUTH_SPEC):
    unit = SourceTextUnit("fixtures/realworld-article-auth.yml", text, len(text.encode()), text_digest(text))
    result = ExplicitDocumentExtractor().extract(source_type, [unit])
    return result, [row.payload(text, unit.content_hash) for row in result.observations]


def fields(row):
    return [json.loads(field["value"]) for field in row["fields"]]


@pytest.mark.parametrize("source_type,kind", [("us_doc", "requirement_document"), ("test_asset", "test_document")])
def test_stripped_article_auth_fixture_preserves_coverage_without_approving_it(source_type, kind):
    result, payloads = project(source_type)
    assert result.files[0]["status"] == "parsed" and result.files[0]["entity_count"] == 14
    assert {(fields(row)[0]["path"], fields(row)[0]["method"]) for row in payloads if "method" in fields(row)[0]} == {
        ("/users/login", "POST"), ("/articles", "GET"), ("/articles", "POST"),
        ("/articles/{slug}", "GET"), ("/articles/{slug}", "PUT"), ("/articles/{slug}", "DELETE")}
    assert all(row["kind"] == kind and row["identity_status"] == "source_occurrence" for row in payloads)
    assert all(not requirement_components(row) for row in result.observations)
    assert all(row["semantic_status"] == "source_projection_not_approved_specification" for row in payloads)
    assert all(field["name"] == "description" for row in payloads for field in row["fields"])
    assert set(result.files[0]["gaps"]) == {
        "supporting_specification_not_approved", "independent_oracle_review_required",
        "openapi_structural_projection_only", "openapi_prose_and_values_omitted",
        "openapi_local_reference_not_expanded", "openapi_non_schema_components_not_projected",
        "openapi_operation_keywords_not_projected", "openapi_schema_keywords_not_projected"}


def test_article_auth_refs_preserve_status_candidates_but_not_wrappers_or_auth_authority():
    _, payloads = project()
    rows = {row["title"]: row for row in payloads}
    created = fields(rows["OpenAPI POST /articles"])
    updated = fields(rows["OpenAPI PUT /articles/{slug}"])
    assert [v["response_status"] for v in created if "response_status" in v] == ["201", "401", "409", "422"]
    assert [v["response_status"] for v in updated if "response_status" in v] == ["200", "401", "403", "404", "422"]
    assert {"section": "requestBody", "reference": "not_expanded"} in created
    assert all(v["reference"] == "not_expanded" and "content" not in v for v in created if "response_status" in v)
    assert {"parameter": "slug", "in": "path", "required": True, "schema": {"type": "string"}} in updated
    assert "openapi_operation_keywords_not_projected" in rows["OpenAPI POST /articles"]["gaps"]
    assert "openapi_operation_keywords_not_projected" not in rows["OpenAPI GET /articles"]["gaps"]
    serialized = json.dumps(payloads)
    assert all(marker not in serialized for marker in ("FIXTURE_ONLY_PASSWORD", "FIXTURE_ONLY_TOKEN", "FIXTURE_ONLY_AUTH_PROSE"))
    assert "Authorization" not in serialized
    assert not any("security" in value for row in payloads for value in fields(row))


def test_article_auth_schema_types_nullable_fields_and_required_lists_are_not_oracles():
    _, payloads = project()
    schemas = {fields(row)[0]["schema_name"]: fields(row)[0]["schema"]
               for row in payloads if "schema_name" in fields(row)[0]}
    properties = lambda schema: {item["name"]: item["schema"] for item in schema["properties"]}
    assert schemas["NewArticle"]["required"] == ["body", "description", "title"]
    article = properties(schemas["Article"])
    assert article["author"] == {"$ref": "not_expanded"}
    assert article["tagList"] == {"type": "array", "items": {"type": "string"}}
    assert article["createdAt"] == {"type": "string"}
    assert properties(schemas["User"])["bio"] == {"type": ["string", "null"]}
    assert properties(schemas["LoginUser"])["password"] == {"type": "string"}
    assert properties(schemas["GenericErrorModel"])["errors"]["additionalProperties"] == {
        "type": "array", "items": {"type": "string"}}


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_article_auth_projection_hashes_exact_spans_and_repeated_reads(newline):
    text = ARTICLE_AUTH_SPEC.replace("\n", newline)
    result, payloads = project(text=text)
    assert (result, payloads) == project(text=text)
    lines = source_lines(text)
    for row in payloads:
        locator = row["locator"]
        assert row["source_file_hash"] == text_digest(text)
        assert row["snippet_hash"] == text_digest("".join(lines[locator["start_line"] - 1:locator["end_line"]]))
        for field in row["fields"]:
            assert locator["start_line"] <= field["start_line"] <= field["end_line"] <= locator["end_line"]
            assert field["snippet_hash"] == text_digest("".join(lines[field["start_line"] - 1:field["end_line"]]))
    # Operation-level observations intentionally cite the whole path item; the
    # response fields must still identify the correct method's exact source line.
    rows = [row for row in payloads if fields(row)[0].get("path") == "/articles/{slug}"]
    expected_start = lines.index("  /articles/{slug}:" + newline) + 1
    expected_end = lines.index("components:" + newline)
    assert len(rows) == 3
    assert all(row["locator"]["start_line"] == expected_start and row["locator"]["end_line"] == expected_end for row in rows)
    denied = [field for row in rows for field in row["fields"] if json.loads(field["value"]).get("response_status") == "403"]
    assert len(denied) == 2 and denied[0]["start_line"] < denied[1]["start_line"]
    assert all(field["start_line"] == field["end_line"] and "'403': {$ref:" in lines[field["start_line"] - 1] for field in denied)


def test_version_stamp_changes_only_new_payload_digest_not_old_payload_or_source_hash():
    _, payloads = project()
    proposed = payloads[0]
    assert proposed["extractor_version"] == "nasus.openapi-document.v1"
    original = {**proposed, "extractor_version": "nasus.explicit-document.v2"}
    before = snapshot_digest(original)
    assert snapshot_digest(proposed) != before
    assert snapshot_digest(original) == before
    assert original["source_file_hash"] == proposed["source_file_hash"]
    assert original["snippet_hash"] == proposed["snippet_hash"]

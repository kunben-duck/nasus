"""Local manifest specimens only; no native target or execution approval."""
from copy import deepcopy
import hashlib
import json

import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_role_fixtures import (
    HTTP_ROLE_FIXTURE_SCHEMA, HttpRoleFixtureInvalid, canonical_http_role_fixture_manifest,
    http_role_fixture_manifest_digest, parse_http_role_fixture_manifest, validate_http_role_fixture_manifest,
)


def role_manifest():
    return {
        "schema": HTTP_ROLE_FIXTURE_SCHEMA,
        "case_id": "case",
        "preconditions_digest": "sha256:" + "a" * 64,
        "roles": {
            "author": {"credential_ref": "credential:" + "1" * 32},
            "other": {"credential_ref": "credential:" + "2" * 32},
            "anonymous": {"credential_ref": None},
        },
        "resource_bindings": {"article": {"owner_role": "author", "recipe_id": "article.v1"}},
        "setup_steps": [
            {"action": "prepare_role", "role": "author"},
            {"action": "prepare_role", "role": "other"},
            {"action": "prepare_resource", "binding_id": "article"},
        ],
        "cleanup_steps": [
            {"action": "cleanup_resource", "binding_id": "article"},
            {"action": "cleanup_role", "role": "other"},
            {"action": "cleanup_role", "role": "author"},
        ],
    }


def test_v2_canonical_bytes_hash_and_independent_copy():
    original = role_manifest()
    canonical = canonical_http_role_fixture_manifest(original)
    digest = http_role_fixture_manifest_digest(original)
    assert digest == "sha256:" + hashlib.sha256(canonical).hexdigest() == acceptance_digest(original)
    assert parse_http_role_fixture_manifest(canonical, expected_digest=digest) == original
    reordered = dict(reversed(list(original.items())))
    reordered["roles"] = dict(reversed(list(original["roles"].items())))
    assert canonical_http_role_fixture_manifest(reordered) == canonical
    saved = validate_http_role_fixture_manifest(original)
    saved["roles"]["author"]["credential_ref"] = "changed"
    saved["setup_steps"][0]["role"] = "changed"
    assert original == role_manifest()
    assert all(word not in canonical.decode() for word in ("password", "token", "headers", "http://", "https://"))


@pytest.mark.parametrize("field", ["headers", "headers_json", "password", "token", "sql", "container", "environment_url", "execution_authorized"])
@pytest.mark.parametrize("location", ["manifest", "role", "resource", "step"])
def test_no_secret_transport_or_execution_extensions(field, location):
    manifest = role_manifest()
    target = {"manifest": manifest, "role": manifest["roles"]["author"],
              "resource": manifest["resource_bindings"]["article"], "step": manifest["setup_steps"][0]}[location]
    target[field] = "private-material-that-must-not-be-echoed"
    with pytest.raises(HttpRoleFixtureInvalid) as caught:
        validate_http_role_fixture_manifest(manifest)
    assert target[field] not in str(caught.value)


@pytest.mark.parametrize("change", [
    "v1", "missing_role", "extra_role", "anonymous_credential", "shared_reference", "raw_reference",
    "nonstring_reference", "resource_as_credential", "credential_as_resource", "unknown_owner",
    "unknown_recipe_field", "url_recipe", "sql_recipe", "shell_recipe", "missing_setup", "duplicate_setup",
    "anonymous_setup", "resource_before_role", "unknown_setup_action", "unknown_cleanup_action",
    "cleanup_before_resource", "missing_cleanup", "duplicate_cleanup", "tuple_steps", "boolean_case",
    "surrogate_case", "extra_resource", "too_many_resources", "nonstring_action", "long_recipe",
])
def test_incomplete_rebound_or_unbounded_recipes_are_rejected(change):
    value = role_manifest()
    if change == "v1": value["schema"] = "nasus.http-fixture-manifest.v1"
    if change == "missing_role": del value["roles"]["other"]
    if change == "extra_role": value["roles"]["fallback"] = {"credential_ref": None}
    if change == "anonymous_credential": value["roles"]["anonymous"] = deepcopy(value["roles"]["author"])
    if change == "shared_reference": value["roles"]["other"] = deepcopy(value["roles"]["author"])
    if change == "raw_reference": value["roles"]["author"]["credential_ref"] = "Bearer private-token"
    if change == "nonstring_reference": value["roles"]["author"]["credential_ref"] = {}
    if change == "resource_as_credential": value["roles"]["author"]["credential_ref"] = "article"
    if change == "credential_as_resource": value["setup_steps"][2]["binding_id"] = value["roles"]["author"]["credential_ref"]
    if change == "unknown_owner": value["resource_bindings"]["article"]["owner_role"] = "fallback"
    if change == "unknown_recipe_field": value["resource_bindings"]["article"]["parameters"] = {"password": "secret"}
    if change == "url_recipe": value["resource_bindings"]["article"]["recipe_id"] = "https://foreign.example/"
    if change == "sql_recipe": value["resource_bindings"]["article"]["recipe_id"] = "DELETE FROM users"
    if change == "shell_recipe": value["resource_bindings"]["article"]["recipe_id"] = "docker exec target"
    if change == "missing_setup": value["setup_steps"].pop()
    if change == "duplicate_setup": value["setup_steps"][1] = deepcopy(value["setup_steps"][0])
    if change == "anonymous_setup": value["setup_steps"][1]["role"] = "anonymous"
    if change == "resource_before_role": value["setup_steps"].reverse()
    if change == "unknown_setup_action": value["setup_steps"][2]["action"] = "execute_test"
    if change == "unknown_cleanup_action": value["cleanup_steps"][0]["action"] = "reset_database"
    if change == "cleanup_before_resource": value["cleanup_steps"].reverse()
    if change == "missing_cleanup": value["cleanup_steps"].pop()
    if change == "duplicate_cleanup": value["cleanup_steps"][2] = deepcopy(value["cleanup_steps"][1])
    if change == "tuple_steps": value["setup_steps"] = tuple(value["setup_steps"])
    if change == "boolean_case": value["case_id"] = True
    if change == "surrogate_case": value["case_id"] = "\ud800"
    if change == "extra_resource": value["resource_bindings"]["uncleaned"] = deepcopy(value["resource_bindings"]["article"])
    if change == "too_many_resources":
        value["resource_bindings"] = {f"item_{index}": {"owner_role": "author", "recipe_id": "article.v1"} for index in range(17)}
    if change == "nonstring_action": value["setup_steps"][0]["action"] = []
    if change == "long_recipe": value["resource_bindings"]["article"]["recipe_id"] = "x" * 65
    with pytest.raises(HttpRoleFixtureInvalid):
        validate_http_role_fixture_manifest(value)


@pytest.mark.parametrize("change", ["whitespace", "order", "newline", "duplicate", "nested_duplicate", "escape",
                                    "bom", "utf16", "trailing", "nan", "infinity", "string", "oversized", "deep"])
def test_strict_readback_rejects_noncanonical_or_ambiguous_wire_bytes(change):
    body = canonical_http_role_fixture_manifest(role_manifest())
    if change == "whitespace": body = json.dumps(role_manifest()).encode()
    if change == "order": body = json.dumps(role_manifest(), separators=(",", ":")).encode()
    if change == "newline": body += b"\n"
    if change == "duplicate": body = body.replace(b'"case_id":"case"', b'"case_id":"other","case_id":"case"')
    if change == "nested_duplicate": body = body.replace(b'"credential_ref":null', b'"credential_ref":"secret","credential_ref":null')
    if change == "escape": body = body.replace(b'"case"', b'"\\u0063ase"')
    if change == "bom": body = b"\xef\xbb\xbf" + body
    if change == "utf16": body = body.decode().encode("utf-16")
    if change == "trailing": body += b"{}"
    if change == "nan": body = body.replace(b"null", b"NaN")
    if change == "infinity": body = body.replace(b"null", b"Infinity")
    if change == "string": body = body.decode()
    if change == "oversized": body = b" " * (32 * 1024 + 1)
    if change == "deep": body = b"[" * 2000 + b"]" * 2000
    with pytest.raises(HttpRoleFixtureInvalid):
        parse_http_role_fixture_manifest(body)


def test_digest_changes_are_not_silently_repaired():
    value = role_manifest()
    original = http_role_fixture_manifest_digest(value)
    value["roles"]["author"]["credential_ref"] = "credential:" + "3" * 32
    assert http_role_fixture_manifest_digest(value) != original
    with pytest.raises(HttpRoleFixtureInvalid):
        parse_http_role_fixture_manifest(canonical_http_role_fixture_manifest(value), expected_digest=original)
    for invalid in (True, "SHA256:" + "a" * 64, {}, "sha256:" + "0" * 64):
        with pytest.raises(HttpRoleFixtureInvalid):
            parse_http_role_fixture_manifest(canonical_http_role_fixture_manifest(value), expected_digest=invalid)


def test_empty_resource_set_and_explicit_anonymous_resources_are_supported():
    value = role_manifest()
    value["resource_bindings"] = {}
    value["setup_steps"].pop()
    value["cleanup_steps"].pop(0)
    assert validate_http_role_fixture_manifest(value) == value
    value = role_manifest()
    value["resource_bindings"]["article"]["owner_role"] = "anonymous"
    value["setup_steps"].insert(0, value["setup_steps"].pop())
    assert validate_http_role_fixture_manifest(value) == value

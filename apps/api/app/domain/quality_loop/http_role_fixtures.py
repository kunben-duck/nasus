"""Bounded public v2 recipes, not authority to register users or execute tests.

Only native catalog recipes are selectable. Credential references are opaque
identities, never resource bindings or interpolation operands. No free-form
request, URL, header, SQL, command, or credential material belongs in this schema.
"""
from copy import deepcopy
import hashlib
import json
import re


HTTP_ROLE_FIXTURE_SCHEMA = "nasus.http-fixture-manifest.v2"
MAX_ROLE_FIXTURE_BYTES = 32 * 1024
MAX_ROLE_RESOURCES = 16
HTTP_FIXTURE_ROLES = ("author", "other", "anonymous")
_IDENTITY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
_REFERENCE = re.compile(r"credential:[0-9a-f]{32}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_INVALID = "HTTP role fixture requires a complete bounded native v2 recipe"


class HttpRoleFixtureInvalid(ValueError):
    pass


def _require(condition):
    if not condition:
        raise HttpRoleFixtureInvalid(_INVALID)


def _identity(value):
    _require(type(value) is str and _IDENTITY.fullmatch(value) is not None)


def validate_role_credential_reference(value):
    _require(type(value) is str and _REFERENCE.fullmatch(value) is not None)
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8", errors="strict")


def validate_http_role_fixture_manifest(value):
    """Validate without coercion, dropping fields, sorting steps, or normalizing IDs."""
    try:
        _require(type(value) is dict and set(value) == {
            "schema", "case_id", "preconditions_digest", "roles", "resource_bindings",
            "setup_steps", "cleanup_steps",
        })
        _require(type(value["schema"]) is str and value["schema"] == HTTP_ROLE_FIXTURE_SCHEMA)
        _identity(value["case_id"])
        _require(type(value["preconditions_digest"]) is str
                 and _DIGEST.fullmatch(value["preconditions_digest"]) is not None)
        roles = value["roles"]
        _require(type(roles) is dict and set(roles) == set(HTTP_FIXTURE_ROLES))
        references = set()
        for role in HTTP_FIXTURE_ROLES:
            entry = roles[role]
            _require(type(entry) is dict and set(entry) == {"credential_ref"})
            reference = entry["credential_ref"]
            if role == "anonymous":
                _require(reference is None)
            else:
                validate_role_credential_reference(reference)
                _require(reference not in references)
                references.add(reference)
        resources = value["resource_bindings"]
        _require(type(resources) is dict and 0 <= len(resources) <= MAX_ROLE_RESOURCES)
        for binding, resource in resources.items():
            _identity(binding)
            _require(binding not in HTTP_FIXTURE_ROLES)
            _require(type(resource) is dict and set(resource) == {"owner_role", "recipe_id"})
            _require(type(resource["owner_role"]) is str and resource["owner_role"] in roles)
            _identity(resource["recipe_id"])
        # Every declared identity is prepared and cleaned exactly once. Cleanup
        # may not revoke a role while that role still owns outstanding resources.
        prepared_roles, prepared_resources = set(), set()
        for phase in ("setup_steps", "cleanup_steps"):
            steps = value[phase]
            _require(type(steps) is list and len(steps) == len(resources) + 2)
            for step in steps:
                _require(type(step) is dict and type(step.get("action")) is str)
                action = step["action"]
                if action in {"prepare_role", "cleanup_role"}:
                    _require(set(step) == {"action", "role"} and type(step["role"]) is str
                             and step["role"] in {"author", "other"})
                    role = step["role"]
                    if phase == "setup_steps":
                        _require(action == "prepare_role" and role not in prepared_roles)
                        prepared_roles.add(role)
                    else:
                        _require(action == "cleanup_role" and role in prepared_roles
                                 and not any(resources[key]["owner_role"] == role for key in prepared_resources))
                        prepared_roles.remove(role)
                else:
                    _require(set(step) == {"action", "binding_id"} and type(step["binding_id"]) is str
                             and step["binding_id"] in resources)
                    binding = step["binding_id"]
                    owner = resources[binding]["owner_role"]
                    if phase == "setup_steps":
                        _require(action == "prepare_resource" and binding not in prepared_resources
                                 and (owner == "anonymous" or owner in prepared_roles))
                        prepared_resources.add(binding)
                    else:
                        _require(action == "cleanup_resource" and binding in prepared_resources)
                        prepared_resources.remove(binding)
            if phase == "setup_steps":
                _require(prepared_roles == {"author", "other"} and prepared_resources == set(resources))
        _require(not prepared_roles and not prepared_resources)
        _require(len(_canonical(value)) <= MAX_ROLE_FIXTURE_BYTES)
        return deepcopy(value)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise HttpRoleFixtureInvalid(_INVALID) from None


def canonical_http_role_fixture_manifest(value):
    return _canonical(validate_http_role_fixture_manifest(value))


def http_role_fixture_manifest_digest(value):
    return "sha256:" + hashlib.sha256(canonical_http_role_fixture_manifest(value)).hexdigest()


def parse_http_role_fixture_manifest(body, *, expected_digest=None):
    """Read exact canonical UTF-8 bytes; reject duplicate keys and alternate encodings."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    try:
        _require(type(body) is bytes and 1 <= len(body) <= MAX_ROLE_FIXTURE_BYTES)
        value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=unique)
        canonical = canonical_http_role_fixture_manifest(value)
        _require(canonical == body)
        if expected_digest is not None:
            _require(type(expected_digest) is str and _DIGEST.fullmatch(expected_digest) is not None
                     and expected_digest == "sha256:" + hashlib.sha256(body).hexdigest())
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise HttpRoleFixtureInvalid(_INVALID) from None

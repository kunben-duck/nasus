"""Static OpenAPI context, deliberately not acceptance criteria or an oracle."""
from __future__ import annotations

import json
import re

from ...domain.system_image.document_projection import OPENAPI_DOCUMENT_EXTRACTOR, DocumentField, DocumentObservation
from .openapi_document_parser import OpenAPIGap, OpenAPISyntax


MAX_OPERATIONS = 500
MAX_SCHEMAS = 400
MAX_FIELDS = 90
MAX_SCHEMA_DEPTH = 8
METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
BASE_GAPS = frozenset({"supporting_specification_not_approved", "independent_oracle_review_required",
                       "openapi_structural_projection_only", "openapi_prose_and_values_omitted"})


def _scalar(node):
    return node.value if node is not None and node.kind == "scalar" else None


def _string(node):
    return node.value if node is not None and node.is_string else None


def _label(value, gaps, *, path=False):
    # Never copy URLs, query credentials, free prose or high-entropy tokens into
    # document titles/fields. Payload values and ref targets are omitted entirely.
    pattern = r"/[A-Za-z0-9_./{}~-]*" if path else r"[A-Za-z_][A-Za-z0-9_.-]{0,63}"
    if (not re.fullmatch(pattern, value) or len(value) > 240
            or re.search(r"[A-Za-z0-9_-]{32,}|(?:sk|ghp|github_pat)[_-]|(?:AKIA|ASIA)[0-9A-Z]{16}|eyJ\w*\.", value, re.I)):
        gaps.add("openapi_sensitive_or_unsupported_label_omitted")
        return "[omitted]"
    return value


def _schema(node, gaps, depth=0):
    if node.kind != "map":
        gaps.add("openapi_schema_form_not_supported")
        return {"coverage": "not_projected"}
    if depth > MAX_SCHEMA_DEPTH:
        raise OpenAPIGap("openapi_schema_projection_depth_limit")
    result = {}
    for key, value in node.members.items():
        if key == "type":
            if _string(value) in TYPES:
                result[key] = value.value
            elif value.kind == "list" and all(_string(item) in TYPES for item in value.items):
                result[key] = [item.value for item in value.items]
            else:
                gaps.add("openapi_schema_form_not_supported")
        elif key == "properties" and value.kind == "map":
            result[key] = [{"name": _label(name, gaps), "schema": _schema(child, gaps, depth + 1)}
                           for name, child in value.members.items()]
        elif key == "required" and value.kind == "list":
            result[key] = [_label(item.value, gaps) for item in value.items if item.is_string]
            if any(not item.is_string for item in value.items):
                gaps.add("openapi_schema_form_not_supported")
        elif key in {"items", "additionalProperties"}:
            if key == "additionalProperties" and value.style is None and _scalar(value) in {"true", "false"}:
                result[key] = value.value == "true"
            else:
                result[key] = _schema(value, gaps, depth + 1)
        elif key in {"allOf", "anyOf", "oneOf"} and value.kind == "list":
            result[key] = [_schema(item, gaps, depth + 1) for item in value.items]
        elif key in {"$ref", "$dynamicRef", "$recursiveRef"}:
            result[key] = "not_expanded"
        elif key not in {"description", "title", "example", "examples", "default", "enum", "const"}:
            gaps.add("openapi_schema_keywords_not_projected")
    return result


def _content(node, gaps):
    if node.kind != "map":
        gaps.add("openapi_invalid_content")
        return []
    result = []
    for media, value in node.members.items():
        safe_media = media if media in {"application/json", "application/xml", "text/plain", "text/html",
                                       "multipart/form-data", "application/x-www-form-urlencoded",
                                       "application/octet-stream", "*/*"} else "[omitted]"
        if safe_media == "[omitted]":
            gaps.add("openapi_media_type_not_projected")
        item = {"media_type": safe_media}
        if value.kind != "map":
            gaps.add("openapi_invalid_content")
        elif value.get("schema") is not None:
            item["schema"] = _schema(value.get("schema"), gaps)
        result.append(item)
    return result


def extract_openapi(source_type, unit, *, json_document):
    syntax = OpenAPISyntax(unit.text, json_document=json_document)
    root = syntax.root
    if root.kind != "map" or root.get("openapi") is None:
        raise OpenAPIGap("not_an_openapi_document")
    version = _string(root.get("openapi"))
    if version is None or not re.fullmatch(r"3\.(?:0|1)\.[0-9]{1,3}", version):
        raise OpenAPIGap("openapi_version_not_supported")
    if root.get("info") is None or root.get("info").kind != "map":
        raise OpenAPIGap("invalid_openapi_structure")
    gaps = set(BASE_GAPS) | syntax.reference_gaps()
    if any(key in root.members for key in ("webhooks", "security")):
        gaps.add("openapi_security_or_webhooks_not_projected")
    if any(key not in {"openapi", "info", "paths", "components", "servers", "tags", "externalDocs"}
           for key in root.members):
        gaps.add("openapi_document_keywords_not_projected")
    kind = "requirement_document" if source_type == "us_doc" else "test_document"
    observations = []

    def observation(title, node, fields, local_gaps):
        if len(fields) > MAX_FIELDS:
            raise OpenAPIGap("openapi_field_limit")
        start, end = syntax.span(node)
        row = DocumentObservation(kind, title, None, unit.relative_path, start, end,
                                  tuple(fields), gaps=tuple(sorted(gaps | local_gaps)), identity_status="source_occurrence",
                                  extractor_version=OPENAPI_DOCUMENT_EXTRACTOR)
        row.payload(unit.text, unit.content_hash)
        observations.append(row)

    def field(node, value):
        value = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(json.dumps(value).encode()) > 32768:
            raise OpenAPIGap("openapi_field_size_limit")
        return DocumentField("description", value, *syntax.span(node))

    paths = root.get("paths")
    if paths is None or paths.kind != "map":
        raise OpenAPIGap("openapi_paths_not_supported")
    count = 0
    for path, path_item in paths.members.items():
        if path.startswith("x-"):
            continue
        if not path.startswith("/") or path_item.kind != "map":
            raise OpenAPIGap("invalid_openapi_path_item")
        for method, operation in path_item.members.items():
            if method not in METHODS:
                if method not in {"summary", "description", "parameters", "servers", "$ref"} and not method.startswith("x-"):
                    gaps.add("openapi_path_item_keyword_not_projected")
                continue
            count += 1
            if count > MAX_OPERATIONS:
                raise OpenAPIGap("openapi_operation_limit")
            if operation.kind != "map":
                raise OpenAPIGap("invalid_openapi_operation")
            local_gaps = set()
            safe_path = _label(path, local_gaps, path=True)
            fields = [field(path_item, {"method": method.upper(), "path": safe_path,
                                        "basis": "supporting_specification_not_approved"})]
            if path_item.get("parameters") is not None:
                local_gaps.add("openapi_path_parameters_not_projected")
            for key, node in operation.members.items():
                if key == "parameters":
                    if node.kind != "list":
                        raise OpenAPIGap("invalid_openapi_parameters")
                    for parameter in node.items:
                        if parameter.kind != "map":
                            raise OpenAPIGap("invalid_openapi_parameters")
                        if parameter.get("$ref") is not None:
                            fields.append(field(parameter, {"parameter": "reference_not_expanded"}))
                            continue
                        name, location = _string(parameter.get("name")), _string(parameter.get("in"))
                        if name is None or location not in {"query", "header", "path", "cookie"}:
                            raise OpenAPIGap("invalid_openapi_parameters")
                        value = {"parameter": _label(name, local_gaps), "in": location}
                        required = parameter.get("required")
                        if required is not None:
                            if required.style is not None or _scalar(required) not in {"true", "false"}:
                                raise OpenAPIGap("invalid_openapi_parameters")
                            value["required"] = required.value == "true"
                        if parameter.get("schema") is not None:
                            value["schema"] = _schema(parameter.get("schema"), local_gaps)
                        if any(key not in {"name", "in", "required", "schema", "description", "example", "examples"}
                               for key in parameter.members):
                            local_gaps.add("openapi_parameter_keywords_not_projected")
                        fields.append(field(parameter, value))
                elif key in {"responses", "requestBody"}:
                    if node.kind != "map":
                        raise OpenAPIGap("invalid_openapi_operation")
                    entries = node.members.items() if key == "responses" else (("requestBody", node),)
                    for label, entry in entries:
                        if key == "responses" and label.startswith("x-"):
                            continue
                        if entry.kind != "map" or (key == "responses" and not re.fullmatch(r"[1-5](?:[0-9]{2}|XX)|default", label)):
                            raise OpenAPIGap("invalid_openapi_responses")
                        value = {"response_status" if key == "responses" else "section": label}
                        if entry.get("$ref") is not None:
                            value["reference"] = "not_expanded"
                        if entry.get("content") is not None:
                            value["content"] = _content(entry.get("content"), local_gaps)
                        if any(key not in {"content", "$ref", "description", "required"} for key in entry.members):
                            local_gaps.add("openapi_body_or_response_keywords_not_projected")
                        required = entry.get("required") if key == "requestBody" else None
                        if required is not None:
                            if required.style is not None or _scalar(required) not in {"true", "false"}:
                                raise OpenAPIGap("invalid_openapi_request_body")
                            value["required"] = required.value == "true"
                        fields.append(field(entry, value))
                elif key not in {"summary", "description", "operationId", "tags", "externalDocs", "deprecated"}:
                    local_gaps.add("openapi_operation_keywords_not_projected")
            if not operation.get("responses") or not operation.get("responses").members:
                local_gaps.add("openapi_missing_responses")
            observation(f"OpenAPI {method.upper()} {safe_path}", path_item, fields, local_gaps)

    components = root.get("components")
    if components is not None:
        if components.kind != "map":
            raise OpenAPIGap("invalid_openapi_components")
        schemas = components.get("schemas")
        if schemas is not None:
            if schemas.kind != "map":
                raise OpenAPIGap("invalid_openapi_components")
            if len(schemas.members) > MAX_SCHEMAS:
                raise OpenAPIGap("openapi_schema_limit")
            for name, schema in schemas.members.items():
                local_gaps = set()
                safe_name = _label(name, local_gaps)
                value = {"schema_name": safe_name, "schema": _schema(schema, local_gaps)}
                observation(f"OpenAPI schema {safe_name}", schema, [field(schema, value)], local_gaps)
        if any(key != "schemas" for key in components.members):
            gaps.add("openapi_non_schema_components_not_projected")
    # A header survives even specs with only unresolved path-item references.
    all_gaps = gaps | {gap for row in observations for gap in row.gaps}
    observation(f"OpenAPI {version} supporting document", root,
                [field(root.get("openapi"), {"openapi": version, "operations_projected": count})], all_gaps)
    return observations, tuple(sorted(all_gaps))

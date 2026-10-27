from __future__ import annotations

import json
from itertools import product

from tree_sitter import Node

from ...domain.system_image.code_analysis import CodeStructureFact, CodeStructureSpan


RULE = "java.import-resolved-annotations.v1"
LOCATOR_RULE = "java.import-resolved-http-locators.v1"
WEB = "org.springframework.web.bind.annotation."
MAPPINGS = {WEB + name + "Mapping": name.upper() for name in ("Get", "Post", "Put", "Patch", "Delete")}
MAPPINGS[WEB + "RequestMapping"] = "ANY"
ANNOTATIONS = {
    "org.springframework.stereotype.Service": "service",
    "org.springframework.boot.autoconfigure.SpringBootApplication": "entrypoint",
    "org.springframework.stereotype.Repository": "database_access",
    "jakarta.persistence.Entity": "database_access",
    "javax.persistence.Entity": "database_access",
    "org.apache.ibatis.annotations.Mapper": "database_access",
    "org.springframework.kafka.annotation.KafkaListener": "event_consumer",
    "org.springframework.amqp.rabbit.annotation.RabbitListener": "event_consumer",
    "org.springframework.jms.annotation.JmsListener": "event_consumer",
    "org.springframework.context.event.EventListener": "event_consumer",
    "org.junit.jupiter.api.Test": "test_entrypoint",
    "org.junit.jupiter.params.ParameterizedTest": "test_entrypoint",
    "org.junit.Test": "test_entrypoint",
    "org.testng.annotations.Test": "test_entrypoint",
}
CONTROLLERS = {WEB + "RestController", "org.springframework.stereotype.Controller"}


def _text(node: Node | None, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8") if node is not None else ""


def _walk(root: Node):
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.named_children))


def java_structure(root: Node, source: bytes, relative_path: str, *, strict_dispatch=False) -> tuple[CodeStructureFact, ...]:
    imports: dict[str, set[str]] = {}
    wildcards: set[str] = set()
    shadowed = {_text(node.child_by_field_name("name"), source) for node in _walk(root)
                if node.type in {"annotation_type_declaration", "class_declaration", "interface_declaration"}}
    for node in root.named_children:
        if node.type != "import_declaration":
            continue
        name = _text(node, source).removeprefix("import").strip().removesuffix(";").strip()
        if name.startswith("static "):
            continue
        if name.endswith(".*"):
            wildcards.add(name[:-1])
        else:
            imports.setdefault(name.rsplit(".", 1)[-1], set()).add(name)

    def resolve(raw):
        if "." in raw:
            return raw
        if raw in shadowed:
            return ""
        if raw in imports:
            return next(iter(imports[raw])) if len(imports[raw]) == 1 else ""
        return next(iter(wildcards)) + raw if len(wildcards) == 1 else ""

    def annotations(declaration):
        modifiers = next((node for node in declaration.named_children if node.type == "modifiers"), None)
        if modifiers is None:
            return []
        result = []
        for annotation in modifiers.named_children:
            if annotation.type not in {"annotation", "marker_annotation"}:
                continue
            raw = _text(annotation.child_by_field_name("name"), source)
            # Multiple wildcard imports need type resolution; familiar names
            # alone must not manufacture endpoints.
            result.append((resolve(raw), annotation))
        return result

    facts: list[CodeStructureFact] = []

    def fact(kind, name, node, **fields):
        if len(facts) >= 50000:
            raise ValueError("Java structural observation limit exceeded")
        facts.append(CodeStructureFact(relative_path, kind, name, node.start_point.row + 1,
                                       node.end_point.row + 1, LOCATOR_RULE if strict_dispatch else RULE, **fields))

    for node in _walk(root):
        if node.type == "package_declaration":
            name = next((child for child in node.named_children if child.type in {"identifier", "scoped_identifier"}), None)
            if name is not None:
                fact("package", _text(name, source), node)
        if node.type not in {"class_declaration", "interface_declaration", "record_declaration", "method_declaration"}:
            continue
        for resolved, annotation in annotations(node):
            if resolved in ANNOTATIONS:
                fact(ANNOTATIONS[resolved], _text(node.child_by_field_name("name"), source), annotation)
        if node.type not in {"class_declaration", "record_declaration"}:
            continue
        class_annotations = annotations(node)
        if not any(name in CONTROLLERS for name, _ in class_annotations):
            continue
        class_mappings = [(name, annotation) for name, annotation in class_annotations if name in MAPPINGS]
        supporting_spans = tuple(CodeStructureSpan(annotation.start_point.row + 1, annotation.end_point.row + 1,
                                                   "controller" if name in CONTROLLERS else "class_mapping")
                                 for name, annotation in class_annotations if name in CONTROLLERS or name in MAPPINGS)
        body = node.child_by_field_name("body")
        for method in body.named_children if body is not None else ():
            if method.type != "method_declaration":
                continue
            mappings = [(name, annotation) for name, annotation in annotations(method) if name in MAPPINGS]
            if not mappings:
                continue
            name, annotation = mappings[0]
            owner = _text(node.child_by_field_name("name"), source) + "." + _text(method.child_by_field_name("name"), source)
            parent = _mapping(*class_mappings[0], source, resolve, strict_dispatch=strict_dispatch) if len(class_mappings) == 1 else ([""], {"ANY"})
            child = _mapping(name, annotation, source, resolve, strict_dispatch=strict_dispatch)
            if len(mappings) != 1 or len(class_mappings) > 1 or parent is None or child is None:
                fact("route", owner, annotation, status="unresolved", supporting_spans=supporting_spans)
                continue
            prefixes, parent_methods = parent
            paths, methods = child
            if parent_methods != {"ANY"}:
                # Spring RequestMethodsRequestCondition.combine uses a union.
                methods = parent_methods if methods == {"ANY"} else methods | parent_methods
            if (not methods or len(prefixes) * len(paths) * len(methods) > 64
                    or any("*" in prefix for prefix in prefixes)):
                fact("route", owner, annotation, status="unresolved", supporting_spans=supporting_spans)
                continue
            for prefix, path, http_method in sorted(product(prefixes, paths, methods)):
                base = "/" + prefix.lstrip("/") if prefix else ""
                route = base.rstrip("/") + "/" + path.lstrip("/") if path else base or "/"
                fact("route", f"{http_method} {route}", annotation, method=http_method, route_path=route,
                     supporting_spans=supporting_spans)
    return tuple(facts)


def _mapping(name: str, annotation: Node, source: bytes, resolve, *, strict_dispatch=False):
    arguments = annotation.child_by_field_name("arguments")
    fields = {}
    if arguments is not None:
        for node in arguments.named_children:
            if node.type in {"line_comment", "block_comment"}:
                continue
            if node.type == "element_value_pair":
                key = _text(node.child_by_field_name("key"), source)
                value = node.child_by_field_name("value")
            else:
                key, value = "value", node
            if key in fields:
                return None
            fields[key] = value
    # A path observation is not enough to prove a params/header/media/version
    # request condition. Preserve the historical inventory rule by default.
    if strict_dispatch and (set(fields) - {"path", "value", "method", "name"}
            or name != WEB + "RequestMapping" and "method" in fields):
        return None
    if "path" in fields and "value" in fields:
        return None
    path_node = fields.get("path", fields.get("value"))
    paths = [""] if path_node is None else _strings(path_node, source)
    if paths is None or any("${" in path or "#{" in path or "//" in path for path in paths):
        return None
    methods = {MAPPINGS[name]}
    if name == WEB + "RequestMapping" and "method" in fields:
        values = fields["method"]
        nodes = values.named_children if values.type == "element_value_array_initializer" else (values,)
        methods = set()
        for node in nodes:
            if node.type in {"line_comment", "block_comment"}:
                continue
            raw = _text(node, source)
            method = raw.rsplit(".", 1)[-1]
            if resolve(raw.rsplit(".", 1)[0]) != WEB + "RequestMethod" or method not in {
                "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE",
            }:
                return None
            methods.add(method)
        methods = methods or {"ANY"}
    return paths, methods


def _strings(node: Node, source: bytes) -> list[str] | None:
    nodes = node.named_children if node.type == "element_value_array_initializer" else (node,)
    result = []
    for value in nodes:
        if value.type in {"line_comment", "block_comment"}:
            continue
        if value.type != "string_literal":
            return None
        try:
            text = json.loads(_text(value, source))
        except ValueError:
            return None
        if not isinstance(text, str) or any(ord(char) < 32 for char in text):
            return None
        result.append(text)
    return result or [""]

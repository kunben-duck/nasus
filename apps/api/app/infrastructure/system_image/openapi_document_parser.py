"""Bounded syntax only: no YAML constructors, aliases, or reference I/O."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import json
import re

import yaml
from yaml import events


MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 40
MAX_NODES = 50000
MAX_SCALAR = 32768
MAX_REFERENCES = 1000
_NUMBER = re.compile(r"[-+]?(?:0o[0-7]+|0x[0-9a-f]+|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[-+]?[0-9]+)?|\.inf|\.nan)", re.I)


class OpenAPIGap(ValueError):
    """Only fixed reason codes, never parser messages containing source bytes."""


@dataclass
class Node:
    kind: str
    start: int
    end: int
    value: str = ""
    style: str | None = None
    members: dict[str, Node] = field(default_factory=dict)
    items: list[Node] = field(default_factory=list)
    key_start: int | None = None

    @property
    def is_string(self):
        # YAML 1.2 core scalars, without constructing Python objects. In
        # particular, unquoted null/booleans/numbers are not reference strings.
        return (self.kind == "scalar" and (self.style is not None or
                (self.value.lower() not in {"", "null", "~", "true", "false"}
                 and not _NUMBER.fullmatch(self.value))))

    def get(self, key):
        return self.members.get(key)


class OpenAPISyntax:
    def __init__(self, text: str, *, json_document: bool):
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise OpenAPIGap("openapi_byte_limit")
        self.text = text
        self.line_starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
        self.nodes = 0
        stream = yaml.parse(text, Loader=yaml.BaseLoader)
        try:
            if not isinstance(next(stream), events.StreamStartEvent):
                raise OpenAPIGap("invalid_openapi_structure")
            if not isinstance(next(stream), events.DocumentStartEvent):
                raise OpenAPIGap("invalid_openapi_structure")
            self.root = self._node(next(stream), stream, 0)
            if not isinstance(next(stream), events.DocumentEndEvent):
                raise OpenAPIGap("invalid_openapi_structure")
            if not isinstance(next(stream), events.StreamEndEvent):
                raise OpenAPIGap("openapi_multiple_documents_not_supported")
            if json_document:
                # YAML is a superset; a .json upload must also be strict JSON.
                json.loads(text, parse_constant=self._invalid_constant)
        except OpenAPIGap:
            raise
        except (yaml.YAMLError, ValueError, StopIteration, RecursionError) as exc:
            raise OpenAPIGap("invalid_openapi_structure") from exc
        finally:
            stream.close()

    @staticmethod
    def _invalid_constant(_value):
        raise OpenAPIGap("invalid_openapi_structure")

    def _node(self, event, stream, depth):
        self.nodes += 1
        if depth > MAX_DEPTH:
            raise OpenAPIGap("openapi_depth_limit")
        if self.nodes > MAX_NODES:
            raise OpenAPIGap("openapi_node_limit")
        if isinstance(event, events.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise OpenAPIGap("openapi_yaml_aliases_not_supported")
        if getattr(event, "tag", None) is not None:
            raise OpenAPIGap("openapi_yaml_tags_not_supported")
        if isinstance(event, events.ScalarEvent):
            if len(event.value) > MAX_SCALAR:
                raise OpenAPIGap("openapi_scalar_limit")
            return Node("scalar", event.start_mark.index, event.end_mark.index, event.value, event.style)
        if not isinstance(event, (events.MappingStartEvent, events.SequenceStartEvent)):
            raise OpenAPIGap("invalid_openapi_structure")
        mapping = isinstance(event, events.MappingStartEvent)
        end_type = events.MappingEndEvent if mapping else events.SequenceEndEvent
        node = Node("map" if mapping else "list", event.start_mark.index, event.end_mark.index)
        while True:
            child_event = next(stream)
            if isinstance(child_event, end_type):
                if event.flow_style:
                    node.end = child_event.end_mark.index
                return node
            child = self._node(child_event, stream, depth + 1)
            if mapping:
                if child.kind != "scalar" or child.value == "<<" or child.value in node.members:
                    raise OpenAPIGap("openapi_ambiguous_mapping")
                value = self._node(next(stream), stream, depth + 1)
                value.key_start = child.start
                node.members[child.value] = value
                node.end = value.end
            else:
                node.items.append(child)
                node.end = child.end

    def span(self, node):
        start = node.start if node.key_start is None else node.key_start
        return bisect_right(self.line_starts, start), bisect_right(self.line_starts, max(start, node.end - 1))

    def reference_gaps(self):
        """Check local pointer existence, but never expand even a local reference."""
        nodes, pending = [], [self.root]
        while pending:
            node = pending.pop()
            nodes.append(node)
            pending.extend(node.members.values())
            pending.extend(node.items)
        dynamic_scope = any(node.kind == "map" and "$id" in node.members for node in nodes)
        gaps, count = set(), 0
        for node in nodes:
            if node.kind != "map":
                continue
            if any(key in node.members for key in ("$dynamicRef", "$recursiveRef", "$dynamicAnchor", "$anchor", "$id")):
                gaps.add("openapi_dynamic_references_not_supported")
            ref = node.get("$ref")
            if ref is None:
                continue
            count += 1
            if count > MAX_REFERENCES:
                raise OpenAPIGap("openapi_reference_limit")
            if not ref.is_string or not ref.value or len(ref.value) > 2048:
                gaps.add("openapi_malformed_reference")
            elif any(marker in ref.value for marker in ("${", "{{", "<%")):
                gaps.add("openapi_dynamic_references_not_supported")
            elif not ref.value.startswith("#"):
                gaps.add("openapi_external_reference_not_fetched")
            elif dynamic_scope:
                gaps.add("openapi_dynamic_references_not_supported")
            elif ref.value != "#" and (not ref.value.startswith("#/") or "%" in ref.value
                                        or re.search(r"~(?![01])", ref.value)):
                gaps.add("openapi_malformed_reference")
            else:
                target = self.root
                for token in ref.value[2:].split("/") if ref.value != "#" else ():
                    token = token.replace("~1", "/").replace("~0", "~")
                    if target.kind == "map":
                        target = target.get(token)
                    elif target.kind == "list" and re.fullmatch(r"0|[1-9][0-9]{0,5}", token):
                        target = target.items[int(token)] if int(token) < len(target.items) else None
                    else:
                        target = None
                    if target is None:
                        break
                gaps.add("openapi_local_reference_not_expanded" if target is not None
                         else "openapi_unresolved_local_reference")
        return gaps

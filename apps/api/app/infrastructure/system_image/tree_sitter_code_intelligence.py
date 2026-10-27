from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path
from typing import Callable, Iterable, Sequence

import tree_sitter_go
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from ...application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeEntityKind,
    CodeIntelligenceResult,
    CodeRelationshipCandidate,
    SourceTextUnit,
)
from ...domain.system_image.code_identity import CodeSymbolKey
from ...domain.system_image.code_provider import CodeProjectionGap, CodeProviderCapabilities, CodeProviderObservation
from .code_symbol_signatures import declaration_key
from ...domain.system_image.code_analysis import CodeFileAnalysis, CodeStructureFact
from .java_structure_inventory import java_structure, RULE as JAVA_STRUCTURE_RULE, LOCATOR_RULE


class _SyntaxFailure(ValueError):
    def __init__(self, count: int) -> None:
        super().__init__("source has syntax errors")
        self.count = count


@dataclass(frozen=True)
class _LanguageGrammar:
    name: str
    language_factory: Callable[[], object]
    symbols: dict[str, CodeEntityKind]
    import_nodes: frozenset[str]
    call_nodes: frozenset[str]


@dataclass(frozen=True)
class _PendingCall:
    source_id: str
    target_name: str
    evidence_ref: str


_COMMON_JS_SYMBOLS: dict[str, CodeEntityKind] = {
    "class_declaration": "class",
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
}
_GRAMMARS: dict[str, _LanguageGrammar] = {
    ".py": _LanguageGrammar(
        name="python",
        language_factory=tree_sitter_python.language,
        symbols={
            "class_definition": "class",
            "function_definition": "function",
        },
        import_nodes=frozenset({"import_statement", "import_from_statement"}),
        call_nodes=frozenset({"call"}),
    ),
    ".js": _LanguageGrammar(
        name="javascript",
        language_factory=tree_sitter_javascript.language,
        symbols=_COMMON_JS_SYMBOLS,
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".jsx": _LanguageGrammar(
        name="javascript",
        language_factory=tree_sitter_javascript.language,
        symbols=_COMMON_JS_SYMBOLS,
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".mjs": _LanguageGrammar(
        name="javascript",
        language_factory=tree_sitter_javascript.language,
        symbols=_COMMON_JS_SYMBOLS,
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".cjs": _LanguageGrammar(
        name="javascript",
        language_factory=tree_sitter_javascript.language,
        symbols=_COMMON_JS_SYMBOLS,
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".ts": _LanguageGrammar(
        name="typescript",
        language_factory=tree_sitter_typescript.language_typescript,
        symbols={
            **_COMMON_JS_SYMBOLS,
            "interface_declaration": "interface",
            "type_alias_declaration": "interface",
            "enum_declaration": "enum",
        },
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".mts": _LanguageGrammar(
        name="typescript",
        language_factory=tree_sitter_typescript.language_typescript,
        symbols={
            **_COMMON_JS_SYMBOLS,
            "interface_declaration": "interface",
            "type_alias_declaration": "interface",
            "enum_declaration": "enum",
        },
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".cts": _LanguageGrammar(
        name="typescript",
        language_factory=tree_sitter_typescript.language_typescript,
        symbols={
            **_COMMON_JS_SYMBOLS,
            "interface_declaration": "interface",
            "type_alias_declaration": "interface",
            "enum_declaration": "enum",
        },
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".tsx": _LanguageGrammar(
        name="tsx",
        language_factory=tree_sitter_typescript.language_tsx,
        symbols={
            **_COMMON_JS_SYMBOLS,
            "interface_declaration": "interface",
            "type_alias_declaration": "interface",
            "enum_declaration": "enum",
        },
        import_nodes=frozenset({"import_statement"}),
        call_nodes=frozenset({"call_expression", "new_expression"}),
    ),
    ".java": _LanguageGrammar(
        name="java",
        language_factory=tree_sitter_java.language,
        symbols={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "class",
            "method_declaration": "method",
            "constructor_declaration": "method",
        },
        import_nodes=frozenset({"import_declaration"}),
        call_nodes=frozenset({"method_invocation", "object_creation_expression"}),
    ),
    ".go": _LanguageGrammar(
        name="go",
        language_factory=tree_sitter_go.language,
        symbols={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_spec": "class",
        },
        import_nodes=frozenset({"import_declaration", "import_spec"}),
        call_nodes=frozenset({"call_expression"}),
    ),
}


class TreeSitterCodeIntelligenceAdapter:
    """Tree-sitter code graph adapter behind Nasus provider-neutral contracts."""

    provider = "tree-sitter"

    def __init__(self, *, strict_http_locators=False) -> None:
        self.provider_version = version("tree-sitter")
        self.strict_http_locators = strict_http_locators

    def capabilities(self) -> CodeProviderCapabilities:
        return CodeProviderCapabilities(self.provider, self.provider_version,
            ("capabilities", "analyze", "analyze_controlled"),
            tuple(sorted({grammar.name for grammar in _GRAMMARS.values()})), "declared")

    def diagnostics(self) -> dict[str, str]:
        return {
            "backend": self.provider,
            "version": self.provider_version,
            "languages": "python,javascript,typescript,tsx,java,go",
            "fallback_policy": "explicit_lexical_evidence",
        }

    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        return self._analyze(units)

    def analyze_controlled(self, units: Sequence[SourceTextUnit], *, check_current: Callable[[], None]) -> CodeIntelligenceResult:
        return self._analyze(units, check_current=check_current)

    def _analyze(self, units: Sequence[SourceTextUnit], *, check_current=None) -> CodeIntelligenceResult:
        entities: dict[str, CodeEntityCandidate] = {}
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate] = {}
        pending_calls: list[_PendingCall] = []
        unsupported_paths: list[str] = []
        file_analyses: list[CodeFileAnalysis] = []
        structural_facts: list[CodeStructureFact] = []
        parser_languages: set[str] = set()
        used_lexical_fallback = False

        for unit in sorted(units, key=lambda item: item.relative_path):
            if check_current is not None:
                check_current()
            grammar = _GRAMMARS.get(Path(unit.relative_path).suffix.lower())
            if grammar is None:
                unsupported_paths.append(unit.relative_path)
                used_lexical_fallback = True
                self._analyze_lexically(unit, entities, relationships)
                file_analyses.append(CodeFileAnalysis(
                    unit.relative_path, Path(unit.relative_path).suffix.lower().lstrip(".") or "unknown",
                    "unsupported", "grammar_unavailable", f"tree-sitter:{self.provider_version}",
                    rules=("lexical-fallback",),
                ))
                continue
            parser_languages.add(grammar.name)
            grammar_package = "tree-sitter-typescript" if grammar.name == "tsx" else f"tree-sitter-{grammar.name}"
            parser_version = f"tree-sitter:{self.provider_version}/{grammar_package}:{version(grammar_package)}"
            if not unit.text_is_lossless:
                file_analyses.append(CodeFileAnalysis(unit.relative_path, grammar.name, "failed", "non_utf8_source",
                                                       parser_version))
                continue
            file_entities: dict[str, CodeEntityCandidate] = {}
            file_relationships: dict[tuple[str, str, str], CodeRelationshipCandidate] = {}
            file_calls: list[_PendingCall] = []
            route_rule = LOCATOR_RULE if self.strict_http_locators else JAVA_STRUCTURE_RULE
            rules = ("syntax", "module", route_rule) if grammar.name == "java" else ("syntax", "module")
            try:
                facts = self._analyze_tree_sitter_unit(unit, grammar, file_entities, file_relationships, file_calls)
            except _SyntaxFailure as exc:
                file_analyses.append(CodeFileAnalysis(unit.relative_path, grammar.name, "failed", "syntax_error",
                                                       parser_version, syntax_errors=exc.count, rules=rules))
                continue
            except (ValueError, RuntimeError, RecursionError):
                file_analyses.append(CodeFileAnalysis(unit.relative_path, grammar.name, "failed", "parser_failed",
                                                       parser_version, rules=rules))
                continue
            for key, entity in file_entities.items():
                entities.setdefault(key, entity)
            relationships.update(file_relationships)
            pending_calls.extend(file_calls)
            structural_facts.extend(facts)
            file_analyses.append(CodeFileAnalysis(unit.relative_path, grammar.name, "parsed", "syntax_valid",
                                                   parser_version, rules=rules))

        if check_current is not None:
            check_current()
        # Repeated declarations with the same scope/signature are not one identity.
        key_counts = Counter(item.symbol_key for item in entities.values() if item.symbol_key is not None)
        children: dict[str, list[str]] = defaultdict(list)
        for edge in relationships.values():
            if edge.relationship_kind == "belongs_to":
                children[edge.to_provider_node_id].append(edge.from_provider_node_id)
        ambiguous = [item.provider_node_id for item in entities.values()
                     if item.symbol_key is not None and key_counts[item.symbol_key] > 1]
        visited: set[str] = set()
        while ambiguous:
            node_id = ambiguous.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            entities[node_id] = replace(entities[node_id], symbol_key=None, identity_status="ambiguous")
            ambiguous.extend(children[node_id])
        self._resolve_calls(entities, relationships, pending_calls)
        if check_current is not None:
            check_current()
        evidence_refs = [
            f"parser:tree-sitter:{self.provider_version}",
            *(f"parser-language:{language}" for language in sorted(parser_languages)),
        ]
        if used_lexical_fallback:
            evidence_refs.append("parser:lexical-fallback")
            evidence_refs.extend(
                f"parser-unsupported:{Path(path).suffix.lower() or 'no-extension'}"
                for path in sorted(set(unsupported_paths))
            )
        gaps = [CodeProjectionGap("dynamic_dispatch_not_covered")]
        failed = sum(item.status == "failed" for item in file_analyses)
        if failed:
            gaps.append(CodeProjectionGap("failed_source_parsing", failed))
        if unsupported_paths:
            gaps.append(CodeProjectionGap("unsupported_source_grammar", len(unsupported_paths)))
        exact = sum(item.location_precision == "exact" for item in entities.values())
        observation = CodeProviderObservation(self.capabilities(), len(entities), len(relationships),
            exact, len(entities) - exact, "partial" if failed or unsupported_paths else "complete", "unknown", tuple(gaps))
        return CodeIntelligenceResult(
            provider=self.provider,
            provider_version=self.provider_version,
            entities=tuple(entities.values()),
            relationships=tuple(relationships.values()),
            evidence_refs=tuple(evidence_refs),
            unsupported_paths=tuple(unsupported_paths),
            file_analyses=tuple(file_analyses),
            structural_facts=tuple(structural_facts),
            provider_observations=(observation,),
        )

    def _analyze_tree_sitter_unit(
        self,
        unit: SourceTextUnit,
        grammar: _LanguageGrammar,
        entities: dict[str, CodeEntityCandidate],
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
        pending_calls: list[_PendingCall],
    ) -> tuple[CodeStructureFact, ...]:
        source = unit.text.encode("utf-8")
        parser = Parser(Language(grammar.language_factory()))
        tree = parser.parse(source)
        if tree.root_node.has_error:
            pending, count = [tree.root_node], 0
            while pending and count < 1000:
                node = pending.pop()
                if node.is_error or node.is_missing:
                    count += 1
                pending.extend(child for child in node.children if child.has_error or child.is_missing or child.is_error)
            raise _SyntaxFailure(max(1, count))
        module_id = self._entity_id(unit.relative_path, "module", unit.relative_path, 1)
        module_evidence = self._evidence(unit.relative_path, 1, max(1, unit.text.count("\n") + 1))
        entities[module_id] = CodeEntityCandidate(
            provider_node_id=module_id,
            name=unit.relative_path,
            qualified_name=unit.relative_path,
            entity_kind="module",
            relative_path=unit.relative_path,
            language=grammar.name,
            start_line=1,
            end_line=max(1, unit.text.count("\n") + 1),
            evidence_refs=(module_evidence, unit.content_hash),
            symbol_key=CodeSymbolKey(unit.relative_path, grammar.name, "module", (), unit.relative_path),
            identity_status="exact",
            location_precision="exact",
        )
        self._walk(
            node=tree.root_node,
            source=source,
            unit=unit,
            grammar=grammar,
            parent_entity_id=module_id,
            parent_entity_kind="module",
            entities=entities,
            relationships=relationships,
            pending_calls=pending_calls,
        )
        facts = (CodeStructureFact(unit.relative_path, "module", unit.relative_path, 1,
                                   max(1, unit.text.count("\n") + 1), "syntax.module.v1"),)
        if grammar.name == "java":
            facts += java_structure(tree.root_node, source, unit.relative_path, strict_dispatch=self.strict_http_locators)
            for fact in facts:
                if fact.kind != "route" or fact.status != "observed":
                    continue
                route_id = self._entity_id(unit.relative_path, "api_route", fact.name, fact.start_line)
                evidence = self._evidence(unit.relative_path, fact.start_line, fact.end_line)
                supporting = tuple(self._evidence(unit.relative_path, span.start_line, span.end_line)
                                   for span in fact.supporting_spans)
                owner = self._route_owner(fact, entities.values())
                symbol_key = CodeSymbolKey(unit.relative_path, grammar.name, "api_route",
                    (*owner.symbol_key.scope, owner.symbol_key.scope_segment), fact.name) if owner else None
                entities[route_id] = CodeEntityCandidate(
                    route_id, fact.name, f"{unit.relative_path}::{fact.name}", "api_route", unit.relative_path,
                    grammar.name, fact.start_line, fact.end_line, (evidence, *supporting, unit.content_hash, fact.rule),
                    symbol_key=symbol_key, identity_status="exact" if symbol_key else "unresolved",
                    location_precision="exact", supporting_spans=fact.supporting_spans,
                )
                self._put_relationship(relationships, CodeRelationshipCandidate(
                    route_id, "belongs_to", owner.provider_node_id if owner else module_id, 0.92, (evidence, *supporting),
                ))
        else:
            self._extract_routes(unit, grammar.name, module_id, entities, relationships)
        return facts

    @staticmethod
    def _route_owner(fact: CodeStructureFact, entities: Iterable[CodeEntityCandidate]) -> CodeEntityCandidate | None:
        owners = [item for item in entities if item.entity_kind == "method"
                  and item.relative_path == fact.relative_path
                  and item.start_line <= fact.start_line <= fact.end_line <= item.end_line]
        if not owners:
            return None
        width = min(item.end_line - item.start_line for item in owners)
        owners = [item for item in owners if item.end_line - item.start_line == width]
        if len(owners) != 1 or owners[0].symbol_key is None or owners[0].identity_status != "exact":
            return None
        return owners[0]

    def _walk(
        self,
        *,
        node: Node,
        source: bytes,
        unit: SourceTextUnit,
        grammar: _LanguageGrammar,
        parent_entity_id: str,
        parent_entity_kind: CodeEntityKind,
        entities: dict[str, CodeEntityCandidate],
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
        pending_calls: list[_PendingCall],
    ) -> None:
        current_parent_id = parent_entity_id
        current_parent_kind = parent_entity_kind
        declared_kind = grammar.symbols.get(node.type)
        if (
            declared_kind is None
            and grammar.name in {"javascript", "typescript", "tsx"}
            and node.type == "variable_declarator"
        ):
            value_node = node.child_by_field_name("value")
            if value_node is not None and value_node.type in {
                "arrow_function",
                "function_expression",
                "generator_function",
            }:
                declared_kind = "function"
        if declared_kind is not None:
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source).strip() if name_node is not None else ""
            if name:
                entity_kind = (
                    "method"
                    if declared_kind == "function" and parent_entity_kind in {"class", "interface"}
                    else declared_kind
                )
                start_line = node.start_point.row + 1
                end_line = node.end_point.row + 1
                entity_id = self._entity_id(unit.relative_path, entity_kind, name, start_line) + f":{node.start_byte}"
                evidence_ref = self._evidence(unit.relative_path, start_line, end_line)
                qualified_name = f"{unit.relative_path}::{name}"
                symbol_key = declaration_key(
                    node=node, source=source, relative_path=unit.relative_path,
                    language=grammar.name, kind=entity_kind, name=name,
                    parent=entities[parent_entity_id].symbol_key,
                )
                entities[entity_id] = CodeEntityCandidate(
                    provider_node_id=entity_id,
                    name=name,
                    qualified_name=qualified_name,
                    entity_kind=entity_kind,
                    relative_path=unit.relative_path,
                    language=grammar.name,
                    start_line=start_line,
                    end_line=end_line,
                    evidence_refs=(evidence_ref, unit.content_hash),
                    symbol_key=symbol_key,
                    identity_status="exact" if symbol_key else "unresolved",
                    location_precision="exact",
                )
                self._put_relationship(
                    relationships,
                    CodeRelationshipCandidate(
                        from_provider_node_id=entity_id,
                        relationship_kind="belongs_to",
                        to_provider_node_id=parent_entity_id,
                        confidence=0.98,
                        evidence_refs=(evidence_ref,),
                    ),
                )
                current_parent_id = entity_id
                current_parent_kind = entity_kind

        if node.type in grammar.import_nodes:
            for dependency in self._dependency_names(grammar.name, self._node_text(node, source)):
                dependency_id = f"{self.provider}:dependency:{grammar.name}:{dependency}"
                evidence_ref = self._evidence(
                    unit.relative_path,
                    node.start_point.row + 1,
                    node.end_point.row + 1,
                )
                entities.setdefault(
                    dependency_id,
                    CodeEntityCandidate(
                        provider_node_id=dependency_id,
                        name=dependency,
                        qualified_name=dependency,
                        entity_kind="dependency",
                        relative_path=unit.relative_path,
                        language=grammar.name,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        evidence_refs=(evidence_ref,),
                        symbol_key=CodeSymbolKey(unit.relative_path, grammar.name, "dependency", (), dependency),
                        identity_status="exact", location_precision="exact",
                    ),
                )
                self._put_relationship(
                    relationships,
                    CodeRelationshipCandidate(
                        from_provider_node_id=parent_entity_id,
                        relationship_kind="depends_on",
                        to_provider_node_id=dependency_id,
                        confidence=0.96,
                        evidence_refs=(evidence_ref,),
                    ),
                )

        if node.type in grammar.call_nodes:
            target_name = self._call_target(node, source)
            if target_name:
                pending_calls.append(
                    _PendingCall(
                        source_id=current_parent_id,
                        target_name=target_name,
                        evidence_ref=self._evidence(
                            unit.relative_path,
                            node.start_point.row + 1,
                            node.end_point.row + 1,
                        ),
                    )
                )

        for child in node.named_children:
            self._walk(
                node=child,
                source=source,
                unit=unit,
                grammar=grammar,
                parent_entity_id=current_parent_id,
                parent_entity_kind=current_parent_kind,
                entities=entities,
                relationships=relationships,
                pending_calls=pending_calls,
            )

    def _analyze_lexically(
        self,
        unit: SourceTextUnit,
        entities: dict[str, CodeEntityCandidate],
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
    ) -> None:
        language = Path(unit.relative_path).suffix.lower().lstrip(".") or "unknown"
        module_id = self._entity_id(unit.relative_path, "module", unit.relative_path, 1)
        entities[module_id] = CodeEntityCandidate(
            provider_node_id=module_id,
            name=unit.relative_path,
            qualified_name=unit.relative_path,
            entity_kind="module",
            relative_path=unit.relative_path,
            language=language,
            start_line=1,
            end_line=max(1, unit.text.count("\n") + 1),
            evidence_refs=(f"file:{unit.relative_path}", unit.content_hash, "parser:lexical-fallback"),
            symbol_key=CodeSymbolKey(unit.relative_path, language, "module", (), unit.relative_path)
                       if unit.text_is_lossless else None,
            identity_status="exact" if unit.text_is_lossless else "unresolved",
            location_precision="exact" if unit.text_is_lossless else "approximate",
        )
        patterns: tuple[tuple[CodeEntityKind, re.Pattern[str]], ...] = (
            ("class", re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")),
            ("function", re.compile(r"\b(?:def|function|fn)\s+([A-Za-z_][A-Za-z0-9_]*)")),
        )
        for entity_kind, pattern in patterns:
            for match in pattern.finditer(unit.text):
                name = match.group(1)
                start_line = unit.text.count("\n", 0, match.start()) + 1
                entity_id = self._entity_id(unit.relative_path, entity_kind, name, start_line)
                evidence_ref = self._evidence(unit.relative_path, start_line, start_line)
                entities[entity_id] = CodeEntityCandidate(
                    provider_node_id=entity_id,
                    name=name,
                    qualified_name=f"{unit.relative_path}::{name}",
                    entity_kind=entity_kind,
                    relative_path=unit.relative_path,
                    language=language,
                    start_line=start_line,
                    end_line=start_line,
                    evidence_refs=(evidence_ref, unit.content_hash, "parser:lexical-fallback"),
                )
                self._put_relationship(
                    relationships,
                    CodeRelationshipCandidate(
                        from_provider_node_id=entity_id,
                        relationship_kind="belongs_to",
                        to_provider_node_id=module_id,
                        confidence=0.62,
                        evidence_refs=(evidence_ref, "parser:lexical-fallback"),
                    ),
                )

    def _extract_routes(
        self,
        unit: SourceTextUnit,
        language: str,
        module_id: str,
        entities: dict[str, CodeEntityCandidate],
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
    ) -> None:
        patterns = {
            "python": re.compile(
                r"@\s*(?:app|router|blueprint)\.(get|post|put|patch|delete|options|head)"
                r"\s*\(\s*['\"]([^'\"]+)['\"]",
                re.IGNORECASE,
            ),
            "javascript": re.compile(
                r"(?:app|router)\.(get|post|put|patch|delete|options|head)"
                r"\s*\(\s*['\"]([^'\"]+)['\"]",
                re.IGNORECASE,
            ),
            "typescript": re.compile(
                r"(?:@(?P<decorator>Get|Post|Put|Patch|Delete)"
                r"|(?:app|router)\.(?P<method>get|post|put|patch|delete))"
                r"\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
                re.IGNORECASE,
            ),
            "tsx": re.compile(
                r"(?:@(?P<decorator>Get|Post|Put|Patch|Delete)"
                r"|(?:app|router)\.(?P<method>get|post|put|patch|delete))"
                r"\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
                re.IGNORECASE,
            ),
            "go": re.compile(
                r"\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\(\s*['\"]([^'\"]+)['\"]",
                re.IGNORECASE,
            ),
        }
        pattern = patterns.get(language)
        if pattern is None:
            return
        for match in pattern.finditer(unit.text):
            if language in {"typescript", "tsx"}:
                method = match.group("decorator") or match.group("method") or "ROUTE"
                path = match.group("path")
            else:
                method, path = match.groups()
            method = method.removesuffix("Mapping").upper()
            start_line = unit.text.count("\n", 0, match.start()) + 1
            route_id = self._entity_id(unit.relative_path, "api_route", f"{method}:{path}", start_line)
            evidence_ref = self._evidence(unit.relative_path, start_line, start_line)
            entities[route_id] = CodeEntityCandidate(
                provider_node_id=route_id,
                name=f"{method} {path}",
                qualified_name=f"{unit.relative_path}::{method}:{path}",
                entity_kind="api_route",
                relative_path=unit.relative_path,
                language=language,
                start_line=start_line,
                end_line=start_line,
                evidence_refs=(evidence_ref, unit.content_hash),
            )
            self._put_relationship(
                relationships,
                CodeRelationshipCandidate(
                    from_provider_node_id=route_id,
                    relationship_kind="belongs_to",
                    to_provider_node_id=module_id,
                    confidence=0.92,
                    evidence_refs=(evidence_ref,),
                ),
            )

    def _resolve_calls(
        self,
        entities: dict[str, CodeEntityCandidate],
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
        pending_calls: Iterable[_PendingCall],
    ) -> None:
        by_name: dict[str, list[str]] = {}
        for entity in entities.values():
            if entity.entity_kind not in {"dependency", "module", "api_route"}:
                by_name.setdefault(entity.name, []).append(entity.provider_node_id)
        for call in pending_calls:
            target_ids = by_name.get(call.target_name, [])
            # Name-only resolution cannot choose among overloads or shadowed names.
            # Leave these edges unresolved for the richer provider / investigation.
            if len(target_ids) != 1 or target_ids[0] == call.source_id:
                continue
            target_id = target_ids[0]
            self._put_relationship(
                relationships,
                CodeRelationshipCandidate(
                    from_provider_node_id=call.source_id,
                    relationship_kind="calls",
                    to_provider_node_id=target_id,
                    confidence=0.82,
                    evidence_refs=(call.evidence_ref,),
                ),
            )

    @staticmethod
    def _dependency_names(language: str, raw: str) -> list[str]:
        if language == "python":
            stripped = raw.strip()
            if stripped.startswith("from "):
                matches = re.findall(r"^from\s+([A-Za-z0-9_.]+)\s+import\b", stripped)
            else:
                import_clause = re.sub(r"^import\s+", "", stripped)
                matches = [
                    item.strip().split()[0]
                    for item in import_clause.split(",")
                    if item.strip()
                ]
        elif language in {"javascript", "typescript", "tsx"}:
            matches = re.findall(r"(?:from\s+|require\s*\()\s*['\"]([^'\"]+)['\"]", raw)
            matches.extend(re.findall(r"import\s*['\"]([^'\"]+)['\"]", raw))
        elif language == "java":
            matches = re.findall(r"import\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\.\*)?)", raw)
        else:
            matches = re.findall(r"['\"]([^'\"]+)['\"]", raw)
        return list(dict.fromkeys(item.strip() for item in matches if item.strip()))

    @staticmethod
    def _call_target(node: Node, source: bytes) -> str:
        function_node = (
            node.child_by_field_name("function")
            or node.child_by_field_name("name")
            or node.child_by_field_name("constructor")
        )
        raw = TreeSitterCodeIntelligenceAdapter._node_text(function_node or node, source)
        identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw)
        return identifiers[-1] if identifiers else ""

    @staticmethod
    def _node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _entity_id(relative_path: str, entity_kind: str, name: str, start_line: int) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.:/-]+", "-", name).strip("-")
        return f"tree-sitter:{relative_path}:{entity_kind}:{normalized}:{start_line}"

    @staticmethod
    def _evidence(relative_path: str, start_line: int, end_line: int) -> str:
        return (
            f"file:{relative_path}#L{start_line}"
            if start_line == end_line
            else f"file:{relative_path}#L{start_line}-L{end_line}"
        )

    @staticmethod
    def _put_relationship(
        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate],
        relationship: CodeRelationshipCandidate,
    ) -> None:
        key = (
            relationship.from_provider_node_id,
            relationship.relationship_kind,
            relationship.to_provider_node_id,
        )
        relationships[key] = relationship


__all__ = ["TreeSitterCodeIntelligenceAdapter"]

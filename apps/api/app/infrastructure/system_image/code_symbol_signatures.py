from __future__ import annotations

from tree_sitter import Node

from ...domain.system_image.code_identity import CodeSymbolKey


def syntax_tokens(node: Node | None, source: bytes) -> tuple[str, ...]:
    if node is None or "comment" in node.type:
        return ()
    if not node.children:
        return (source[node.start_byte:node.end_byte].decode("utf-8"),)
    return tuple(token for child in node.children for token in syntax_tokens(child, source))


def declaration_key(
    *, node: Node, source: bytes, relative_path: str, language: str,
    kind: str, name: str, parent: CodeSymbolKey | None,
) -> CodeSymbolKey | None:
    if node.has_error or parent is None:
        return None
    scope = () if parent.kind == "module" else (*parent.scope, parent.scope_segment)
    receiver = node.child_by_field_name("receiver")
    if receiver is not None:
        # Go methods are top-level AST declarations; receiver type is their scope.
        scope = (*scope, "receiver:" + " ".join(_typed_parameters(receiver, source)))
    parameters = node.child_by_field_name("parameters")
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value is not None:
            parameters = value.child_by_field_name("parameters") or value.child_by_field_name("parameter")
    if language in {"java", "go"}:
        signature = _typed_parameters(parameters, source)
    else:
        signature = _parameters_without_defaults(parameters, source)
    type_parameters = syntax_tokens(node.child_by_field_name("type_parameters"), source)
    if kind in {"function", "method"}:
        signature = (
            "constructor" if node.type == "constructor_declaration" else "callable",
            *type_parameters, "(", *signature, ")",
        )
    else:
        signature = type_parameters
    return CodeSymbolKey(relative_path, language, kind, scope, name, signature)


def _typed_parameters(node: Node | None, source: bytes) -> tuple[str, ...]:
    if node is None:
        return ()
    result: list[str] = []
    for parameter in node.named_children:
        if "comment" in parameter.type:
            continue
        type_node = parameter.child_by_field_name("type")
        # Java spread parameters expose the type as a named child, not a field.
        if type_node is None and parameter.type == "spread_parameter":
            type_node = next((child for child in parameter.named_children
                              if child.type not in {"modifiers", "variable_declarator"}), None)
        if type_node is None:
            result.extend(syntax_tokens(parameter, source))
        else:
            tokens = syntax_tokens(type_node, source)
            dimensions = syntax_tokens(parameter.child_by_field_name("dimensions"), source)
            variadic = ("...",) if parameter.type in {"spread_parameter", "variadic_parameter_declaration"} else ()
            # Go permits `a, b int`: both parameters are part of the signature.
            names = parameter.children_by_field_name("name")
            for _ in range(max(1, len(names))):
                result.extend((*tokens, *dimensions, *variadic, ";"))
    return tuple(result)


def _parameters_without_defaults(node: Node | None, source: bytes) -> tuple[str, ...]:
    if node is None:
        return ()
    if "comment" in node.type:
        return ()
    if node.type in {"default_parameter", "typed_default_parameter", "required_parameter", "optional_parameter", "assignment_pattern"}:
        value = node.child_by_field_name("value") or node.child_by_field_name("right")
        return tuple(token for child in node.children if child != value and child.type != "="
                     for token in _parameters_without_defaults(child, source))
    if not node.children:
        return syntax_tokens(node, source)
    return tuple(token for child in node.children for token in _parameters_without_defaults(child, source))

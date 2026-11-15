"""Bounded Django Ninja route observations from frozen Python ASTs only."""
import ast
from collections import Counter
from pathlib import PurePosixPath
import sys

from ...domain.shared.native_build_source import byte_digest
from ...domain.system_image.evidence import source_lines, text_digest


RULE = "python.django-ninja-http-locators.v1"
SCHEMA = "nasus.frozen-http-route-inventory.v3"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


class DjangoHttpLocators:
    provider = "python-ast-django-ninja"
    provider_version = "ast-" + ".".join(map(str, sys.version_info[:2])) + "/nasus-v1"

    def __init__(self, files, *, require_access):
        self.files = {file.path: file for file in files}
        self.trees, self.lines, self.imports, self.values = {}, {}, {}, {}
        self.observations, self.routes = [], []
        self.check = require_access
        if len(self.files) != len(files) or len(files) > 1000:
            raise ValueError("Django locator input must be a complete bounded source roster")
        for file in files:
            self.check()
            python = file.path.endswith(".py")
            status, reason = "unsupported", "not_python"
            if python:
                try:
                    text = file.body.decode("utf-8", errors="strict")
                    tree = ast.parse(text, filename=file.path)
                    self.trees[file.path], self.lines[file.path] = tree, source_lines(text)
                    self._symbols(file.path, tree)
                    status, reason = "parsed", "python_ast"
                except (SyntaxError, UnicodeError, RecursionError, ValueError):
                    status, reason = "failed", "python_syntax_or_encoding"
            self.observations.append({"relative_path": file.path, "language": "python" if python else PurePosixPath(file.path).suffix.lstrip(".") or "unknown",
                "status": status, "reason": reason, "parser_version": self.provider_version,
                "syntax_errors": int(status == "failed"), "rules": [RULE] if python else [],
                "source_file_hash": byte_digest(file.body), "byte_count": len(file.body)})

    def _symbols(self, path, tree):
        imports, values, writes, wildcard = {}, {}, Counter(), False
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom) and not statement.level:
                for alias in statement.names:
                    wildcard = wildcard or alias.name == "*"
                    name = alias.asname or alias.name
                    imports[name] = (statement.module or "") + "." + alias.name
                    writes[name] += 1
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imports[name] = alias.name if alias.asname else name
                    writes[name] += 1
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = (statement.value, statement)
                        writes[target.id] += 1
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                writes[statement.name] += 1
            else:
                # A conditional/reassignment cannot become a static constant.
                for node in ast.walk(statement):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                        if node.id == "urlpatterns" and any(isinstance(parent, ast.AugAssign)
                                and isinstance(parent.op, ast.Add) and parent.target is node for parent in ast.walk(statement)):
                            continue
                        writes[node.id] += 2
        self.imports[path] = {key: value for key, value in imports.items() if writes[key] == 1 and not wildcard}
        self.values[path] = {key: value for key, value in values.items() if writes[key] == 1 and not wildcard}

    def _name(self, path, node):
        if isinstance(node, ast.Name):
            return self.imports[path].get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = self._name(path, node.value)
            return parent + "." + node.attr if parent else None
        return None

    def _string(self, path, node, seen=()):
        if len(seen) > 16:
            return None, []
        if isinstance(node, ast.Constant) and type(node.value) is str:
            return node.value, [(path, node)]
        if isinstance(node, ast.Name) and node.id not in seen and node.id in self.values[path]:
            value, statement = self.values[path][node.id]
            if statement.lineno >= node.lineno:
                return None, []
            text, spans = self._string(path, value, (*seen, node.id))
            return text, [(path, statement), *spans]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, ls = self._string(path, node.left, seen)
            right, rs = self._string(path, node.right, seen)
            return (left + right if left is not None and right is not None else None), [*ls, *rs]
        if isinstance(node, ast.JoinedStr):
            parts, spans = [], []
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    if part.conversion != -1 or part.format_spec is not None:
                        return None, []
                    part = part.value
                value, support = self._string(path, part, seen)
                if value is None:
                    return None, []
                parts.append(value)
                spans.extend(support)
            return "".join(parts), spans
        return None, []

    def _constructor(self, path, name):
        value = self.values[path].get(name)
        if value and isinstance(value[0], ast.Call):
            return self._name(path, value[0].func)
        return None

    def _span(self, path, node):
        start, end = node.lineno, node.end_lineno
        return {"relative_path": path, "source_file_hash": byte_digest(self.files[path].body),
            "start_line": start, "end_line": end,
            "snippet_hash": text_digest("".join(self.lines[path][start - 1:end]))}

    def _emit(self, path, node, *, method="ANY", route=None, support=(), prefix=None):
        if len(self.routes) >= 50000 or len(support) > 256:
            raise ValueError("Django locator inventory exceeds its complete bound")
        if prefix is not None and any(c in prefix for c in "{}?"):
            prefix = None
        value = {**self._span(path, node), "kind": "route", "name": getattr(node, "name", "mount"),
            "rule": RULE, "status": "observed" if route is not None else "unresolved",
            "method": method if route is not None else None, "route_path": route,
            "supporting_spans": [{**self._span(p, n), "role": "route_support"} for p, n in support]}
        if route is None:
            value.update(unresolved_match_scope=None, unresolved_path_prefix=prefix)
        self.routes.append(value)

    @staticmethod
    def _join(prefix, suffix):
        if prefix is None or suffix is None or any(c in prefix + suffix for c in "\\?#%*"):
            return None
        return "/" + "/".join(part.strip("/") for part in (prefix, suffix) if part.strip("/")) + (
            "/" if suffix.endswith("/") and (prefix.strip("/") or suffix.strip("/")) else "")

    def _module(self, reference):
        if not reference or "." not in reference:
            return None
        module, symbol = reference.rsplit(".", 1)
        relative = module.replace(".", "/") + ".py"
        candidates = [path for path in self.trees if path == relative or path.endswith("/" + relative)]
        return (candidates[0], symbol) if len(candidates) == 1 else None

    def _router(self, path, name, prefix, support, trail=()):
        self.check()
        if (path, name) in trail or len(trail) >= 16:
            anchor_path, anchor = support[-1]
            self._emit(anchor_path, anchor, support=support, prefix=prefix)
            return
        if self._constructor(path, name) not in {"ninja.Router", "ninja.NinjaAPI"}:
            anchor_path, anchor = support[-1]
            self._emit(anchor_path, anchor, support=support, prefix=prefix)
            return
        tree = self.trees[path]
        top = {id(statement.value) for statement in tree.body if isinstance(statement, ast.Expr)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_router"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == name):
                prefix_value, spans = self._string(path, node.args[0] if node.args else None)
                mounted = self._join(prefix, prefix_value)
                target_node = node.args[1] if len(node.args) == 2 else None
                reference, _ = self._string(path, target_node)
                reference = reference or self._name(path, target_node)
                target = (path, reference) if reference in self.values[path] else self._module(reference)
                if id(node) not in top or target is None or mounted is None or node.keywords:
                    self._emit(path, node, support=support, prefix=mounted if id(node) in top else prefix)
                else:
                    self._router(*target, mounted, [*support, (path, node), *spans], (*trail, (path, name)))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == name
                        and decorator.func.attr in METHODS):
                    continue
                suffix, spans = self._string(path, decorator.args[0] if len(decorator.args) == 1 else None)
                route = self._join(prefix, suffix) if node in tree.body and len(node.decorator_list) == 1 else None
                self._emit(path, decorator, method=decorator.func.attr.upper(), route=route,
                    support=[*support, *spans, (path, node)], prefix=prefix)

    def inspect(self):
        for path, tree in self.trees.items():
            self.check()
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and self._name(path, node.func) == "django.urls.path"
                        and len(node.args) >= 2 and isinstance(node.args[1], ast.Attribute)
                        and node.args[1].attr == "urls" and isinstance(node.args[1].value, ast.Name)):
                    continue
                name = node.args[1].value.id
                if self._constructor(path, name) != "ninja.NinjaAPI":
                    continue
                pattern = self.values[path].get("urlpatterns")
                prefix, spans = self._string(path, node.args[0])
                in_list = pattern is not None and isinstance(pattern[0], (ast.List, ast.Tuple)) and node in pattern[0].elts
                if prefix is None or not in_list:
                    self._emit(path, node)
                else:
                    self._router(path, name, self._join("", prefix), [(path, node), *spans])
        return {"files": sorted(self.observations, key=lambda item: item["relative_path"]), "routes": self.routes}

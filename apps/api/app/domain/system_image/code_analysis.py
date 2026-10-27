from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


STRUCTURE_KINDS = frozenset({
    "module", "package", "service", "entrypoint", "route", "event_consumer",
    "database_access", "test_entrypoint", "configuration_boundary",
})


def analysis_path(path: str) -> None:
    value = PurePosixPath(path)
    if (not value.parts or value.is_absolute() or ".." in value.parts or "\\" in path
            or value.as_posix() != path or len(path.encode("utf-8")) > 4096
            or any(ord(char) < 32 for char in path)):
        raise ValueError("invalid code analysis path")


@dataclass(frozen=True)
class CodeFileAnalysis:
    relative_path: str
    language: str
    status: str
    reason: str
    parser_version: str
    syntax_errors: int = 0
    rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        analysis_path(self.relative_path)
        if self.status not in {"parsed", "unsupported", "failed"}:
            raise ValueError("invalid parser status")
        if not self.language or not self.reason or not self.parser_version:
            raise ValueError("parser observations require provenance")
        if type(self.syntax_errors) is not int or not 0 <= self.syntax_errors <= 1000:
            raise ValueError("invalid syntax error count")
        if self.status == "parsed" and self.syntax_errors:
            raise ValueError("syntax errors cannot be reported as a successful parse")
        if not isinstance(self.rules, tuple) or len(self.rules) > 32:
            raise ValueError("invalid analysis rule coverage")


@dataclass(frozen=True)
class CodeStructureSpan:
    start_line: int
    end_line: int
    role: str

    def __post_init__(self) -> None:
        if (type(self.start_line) is not int or type(self.end_line) is not int
                or not 1 <= self.start_line <= self.end_line or self.role not in {"controller", "class_mapping"}):
            raise ValueError("invalid supporting source span")


@dataclass(frozen=True)
class CodeStructureFact:
    relative_path: str
    kind: str
    name: str
    start_line: int
    end_line: int
    rule: str
    status: str = "observed"
    method: str | None = None
    route_path: str | None = None
    supporting_spans: tuple[CodeStructureSpan, ...] = ()

    def __post_init__(self) -> None:
        analysis_path(self.relative_path)
        if self.kind not in STRUCTURE_KINDS or self.status not in {"observed", "unresolved", "path_hint"}:
            raise ValueError("invalid structural observation")
        if not self.name or len(self.name) > 4096 or not self.rule:
            raise ValueError("structural observation requires a bounded name and rule")
        if type(self.start_line) is not int or type(self.end_line) is not int or not 1 <= self.start_line <= self.end_line:
            raise ValueError("structural observation requires source lines")
        if not isinstance(self.supporting_spans, tuple) or len(self.supporting_spans) > 16:
            raise ValueError("invalid supporting source spans")
        if self.kind == "route" and self.status == "observed":
            if self.method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "ANY"}:
                raise ValueError("invalid route method")
            if self.route_path is None or not self.route_path.startswith("/"):
                raise ValueError("resolved routes require a static path")

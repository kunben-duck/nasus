from __future__ import annotations

import csv
import ast
import io
import re
from pathlib import PurePosixPath

from ...application.system_image.document_projections import DocumentExtraction
from ...domain.system_image.document_projection import DocumentField, DocumentObservation, disambiguate_documents
from ...domain.system_image.document_components import component_identifier, requirement_components
from ...domain.system_image.evidence import source_lines


IDENTIFIER = r"(?:US|REQ|TC|TEST)-[A-Za-z0-9][A-Za-z0-9_.-]*"
DECLARATION = re.compile(r"^\s*(?:#{1,6}\s+)?(" + IDENTIFIER + r")(?:[ \t]*(?::|：|[ \t]+-[ \t]+|[ \t])[ \t]*(.*?))?[ \t]*$", re.I)
REFERENCE = re.compile(r"(?<![A-Za-z0-9_-])(?:US|REQ)-[A-Za-z0-9][A-Za-z0-9_.-]*", re.I)
LABELS = {
    "description": "description", "描述": "description",
    "acceptance criteria": "acceptance_criterion", "验收条件": "acceptance_criterion", "验收标准": "acceptance_criterion",
    "business rules": "business_rule", "business rule": "business_rule", "业务规则": "business_rule",
    "preconditions": "precondition", "前置条件": "precondition",
    "steps": "step", "步骤": "step", "测试步骤": "step",
    "expected result": "expected_result", "expected results": "expected_result", "预期结果": "expected_result",
    "references": "reference", "需求引用": "reference", "requirement ids": "reference",
}


class ExplicitDocumentExtractor:
    """Bounded source projection, not a semantic relation or acceptance judge."""

    def extract(self, source_type, units):
        if source_type not in {"us_doc", "test_asset"}:
            raise ValueError("unsupported document source type")
        if len({u.relative_path for u in units}) != len(units):
            raise ValueError("duplicate document source path")
        observations, files, entity_count = [], [], 0
        for unit in units:
            suffix = PurePosixPath(unit.relative_path).suffix.lower()
            supported = suffix in {".md", ".markdown", ".txt", ".csv"} or (source_type == "test_asset" and suffix == ".py")
            if not supported or not unit.text_is_lossless:
                files.append({"path": unit.relative_path, "status": "unsupported",
                              "reason": "exact_source_locator_adapter_required"})
                continue
            if len(unit.text.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("document extraction exceeds 2 MiB per file")
            try:
                rows = (self._python_tests(unit) if suffix == ".py" else self._csv(source_type, unit)
                        if suffix == ".csv" else self._markdown(source_type, unit))
                row_count = len(rows) + sum(len(requirement_components(row)) for row in rows)
            except (csv.Error, ValueError, SyntaxError, RecursionError):
                # A malformed optional source remains an explicit gap, never a successful parse.
                files.append({"path": unit.relative_path, "status": "failed", "reason": "invalid_document_structure"})
                continue
            if row_count > 1000 or entity_count + row_count > 10000:
                raise ValueError("document extraction exceeds entity limit")
            entity_count += row_count
            observations.extend(rows)
            files.append({"path": unit.relative_path, "status": "parsed", "entity_count": row_count})
        return DocumentExtraction(disambiguate_documents(tuple(observations)), tuple(files))

    @staticmethod
    def _observation(source_type, unit, external_id, title, start, end, fields, *, anonymous=False):
        kind = "requirement" if source_type == "us_doc" else "test_case"
        names = {field.name for field in fields}
        required = {"acceptance_criterion"} if source_type == "us_doc" else {"step", "expected_result"}
        gaps = tuple("missing_" + name for name in sorted(required - names))
        if anonymous:
            kind = "requirement_document" if source_type == "us_doc" else "test_document"
            gaps += ("no_explicit_record_identity",)
        references = tuple(sorted({match.upper() for field in fields if field.name == "reference"
                                   for match in REFERENCE.findall(field.value)}))
        observation = DocumentObservation(kind, title, external_id, unit.relative_path, start, end,
            tuple(fields), references, gaps, "source_occurrence" if anonymous else "explicit_id")
        observation.payload(unit.text, unit.content_hash)
        return observation

    def _markdown(self, source_type, unit):
        lines = source_lines(unit.text)
        declarations, fence = [], None
        for i, line in enumerate(lines):
            previous, fence = fence, self._markdown_fence(line, fence)
            if previous is not None or fence is not None or re.match(r"^(?: {4}|\t)", line):
                continue
            match = DECLARATION.match(line)
            if match and (match[1].upper().startswith(("US-", "REQ-")) == (source_type == "us_doc")):
                declarations.append((i, match[1].upper(), (match[2] or match[1]).strip()))
        if not declarations:
            # Retain an evidenced document but do not invent US/case semantics.
            text = unit.text.strip()
            if not text:
                return []
            fields = (DocumentField("description", text, 1, len(lines)),)
            return [self._observation(source_type, unit, None, PurePosixPath(unit.relative_path).name,
                                     1, len(lines), fields, anonymous=True)]
        result = []
        for n, (start, external_id, title) in enumerate(declarations):
            end = declarations[n + 1][0] if n + 1 < len(declarations) else len(lines)
            fields, name, fence = [], "description", None
            for index in range(start + 1, end):
                previous, fence = fence, self._markdown_fence(lines[index], fence)
                code_line = previous is not None or fence is not None or bool(re.match(r"^(?: {4}|\t)", lines[index]))
                raw = lines[index].strip()
                if not raw:
                    continue
                cleaned = re.sub(r"^#{1,6}\s+", "", raw)
                label, separator, value = re.sub(r"^[-*]\s+", "", cleaned).partition(":")
                if not separator:
                    label, separator, value = cleaned.partition("：")
                section = LABELS.get(label.rstrip(":：").strip().casefold()) if not code_line else None
                component_heading = (source_type == "us_doc" and not code_line
                                     and component_identifier(name, cleaned) is not None)
                if raw.startswith("#") and not section and not code_line and not component_heading:
                    name = "description"
                if section:
                    name = section
                    if not separator or not value.strip():
                        continue
                    cleaned = value.strip()
                if code_line:
                    field_name = "description"
                else:
                    field_name = name
                fields.append(DocumentField(field_name, cleaned, index + 1, index + 1))
            result.append(self._observation(source_type, unit, external_id, title, start + 1, end, fields))
        return result

    @staticmethod
    def _markdown_fence(line, current):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if current is not None:
            if match and match[1][0] == current[0] and len(match[1]) >= current[1] and not match[2].strip():
                return None
            return current
        if match and not (match[1][0] == "`" and "`" in match[2]):
            return match[1][0], len(match[1])
        return None

    @staticmethod
    def _python_tests(unit):
        tree = ast.parse(unit.text)
        if sum(1 for _ in ast.walk(tree)) > 50000:
            raise ValueError("Python test source exceeds syntax node limit")
        lines, result = source_lines(unit.text), []
        functions = [(node, node.name) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        functions += [(node, f"{cls.name}.{node.name}") for cls in tree.body if isinstance(cls, ast.ClassDef)
                      for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node, name in functions:
            if not node.name.startswith("test_"):
                continue
            start, end = node.lineno, node.end_lineno
            text = "".join(lines[start - 1:end])
            item = DocumentObservation("test_script", name, None, unit.relative_path, start, end,
                (DocumentField("description", text, start, end),), gaps=("script_not_executed", "unreviewed_script_oracle"),
                identity_status="source_occurrence")
            item.payload(unit.text, unit.content_hash)
            result.append(item)
        return result

    def _csv(self, source_type, unit):
        reader = csv.reader(io.StringIO(unit.text, newline=""), strict=True)
        header = next(reader, None)
        if header is None:
            return []
        aliases = {"id": "id", "编号": "id", "title": "title", "标题": "title",
                   **LABELS, "acceptance_criteria": "acceptance_criterion", "business_rules": "business_rule", "expected_result": "expected_result",
                   "requirement_ids": "reference"}
        columns = [aliases.get(value.strip().casefold()) for value in header]
        known = [value for value in columns if value]
        if not {"id", "title"} <= set(known) or len(set(known)) != len(known):
            raise ValueError("CSV needs unambiguous id and title columns")
        result, previous = [], reader.line_num
        for row in reader:
            start, end = previous + 1, reader.line_num
            previous = end
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError("CSV column count mismatch")
            values = {key: value.strip() for key, value in zip(columns, row) if key}
            identifier = values["id"].upper()
            if not re.fullmatch(IDENTIFIER, identifier) or (identifier.startswith(("US-", "REQ-")) != (source_type == "us_doc")):
                raise ValueError("CSV source identity kind mismatch")
            fields = [DocumentField(key, value, start, end) for key, value in values.items()
                      if key not in {"id", "title"} and value]
            result.append(self._observation(source_type, unit, identifier, values["title"], start, end, fields))
        return result

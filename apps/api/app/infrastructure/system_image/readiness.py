from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

from ...application.system_image.source_ports import CodeIntelligencePort, SourceTextUnit
from .git_source_connector import GitSourceConnector
from .tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


class GitSourceConnectorReadinessProbe:
    name = "git_source_connector"

    def __init__(self, connector: GitSourceConnector | None = None) -> None:
        self._connector = connector or GitSourceConnector()

    def check(self) -> dict[str, str]:
        if not self._connector.git_binary:
            raise RuntimeError("Git executable is unavailable")
        result = subprocess.run(
            [self._connector.git_binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "Git executable check failed").strip())

        self._connector.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self._connector.cache_dir, prefix=".readiness-", delete=False) as handle:
            readiness_path = handle.name
        os.unlink(readiness_path)
        return {
            "backend": "git",
            "version": result.stdout.strip(),
            "cache": str(self._connector.cache_dir),
            "host_policy": "allowlist" if self._connector.allowed_hosts else "development-unrestricted",
        }


class CodeIntelligenceReadinessProbe:
    name = "code_intelligence"

    def __init__(
        self,
        adapter: CodeIntelligencePort | None = None,
    ) -> None:
        self._adapter = adapter or TreeSitterCodeIntelligenceAdapter()

    def check(self) -> dict[str, str]:
        source = "def nasus_readiness():\n    return True\n"
        structural_adapter = getattr(self._adapter, "primary", self._adapter)
        result = structural_adapter.analyze(
            (
                SourceTextUnit(
                    relative_path="readiness.py",
                    text=source,
                    byte_count=len(source.encode("utf-8")),
                    content_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                ),
            )
        )
        if not any(
            entity.entity_kind == "function"
            and entity.name == "nasus_readiness"
            for entity in result.entities
        ):
            raise RuntimeError("Tree-sitter smoke parse did not produce the expected function")
        if not any(
            evidence.startswith("parser:tree-sitter:")
            for evidence in result.evidence_refs
        ):
            raise RuntimeError("Tree-sitter parser evidence is missing")
        details = {
            "backend": result.provider,
            "version": result.provider_version,
            "languages": "python,javascript,typescript,tsx,java,go",
            "fallback_policy": "explicit_lexical_evidence",
        }
        diagnostics = getattr(self._adapter, "diagnostics", None)
        if callable(diagnostics):
            reported = diagnostics()
            if not isinstance(reported, dict):
                raise RuntimeError("code intelligence diagnostics are invalid")
            details.update({str(key): str(value) for key, value in reported.items()})
        return details


__all__ = [
    "CodeIntelligenceReadinessProbe",
    "GitSourceConnectorReadinessProbe",
]

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${NASUS_VERIFY_PYTHON:-$ROOT_DIR/.venv/bin/python}"
CODE_GRAPH_BINARY="${NASUS_CODE_GRAPH_BINARY:-$ROOT_DIR/.venv/bin/codebase-memory-mcp}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python runtime is unavailable: $PYTHON_BIN" >&2
  exit 1
fi

cd "$ROOT_DIR"
NASUS_CODE_GRAPH_BINARY="$CODE_GRAPH_BINARY" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import (
    CodebaseMemoryCodeIntelligenceAdapter,
)


def source_unit(root: Path, relative_path: str) -> SourceTextUnit:
    path = root / relative_path
    content = path.read_text(encoding="utf-8")
    encoded = content.encode("utf-8")
    return SourceTextUnit(
        relative_path=relative_path,
        text=content,
        byte_count=len(encoded),
        content_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        source_root=str(root),
    )


with tempfile.TemporaryDirectory(prefix="nasus-code-graph-contract-") as temporary:
    root = Path(temporary) / "repository"
    root.mkdir()
    (root / "authorization.py").write_text(
        "def authorize(account_id: str) -> bool:\n"
        "    return bool(account_id)\n",
        encoding="utf-8",
    )
    (root / "payments.py").write_text(
        "from authorization import authorize\n\n"
        "class PaymentService:\n"
        "    def create(self, account_id: str) -> bool:\n"
        "        return authorize(account_id)\n",
        encoding="utf-8",
    )

    binary = os.environ["NASUS_CODE_GRAPH_BINARY"]
    adapter = CodebaseMemoryCodeIntelligenceAdapter(
        CodeGraphConfig(
            mode="required",
            binary=binary,
            index_mode="fast",
            timeout_seconds=180.0,
            max_entities=200,
            max_relationships=500,
            page_size=100,
            cache_dir=Path(temporary) / "cache",
        )
    )
    result = adapter.analyze(
        [
            source_unit(root, "authorization.py"),
            source_unit(root, "payments.py"),
        ]
    )

    if len(result.entities) < 4:
        raise SystemExit(
            f"Code graph returned too few entities: {len(result.entities)}"
        )
    if not result.relationships:
        raise SystemExit("Code graph returned no relationships for the contract repository")
    leaked = [
        entity.qualified_name
        for entity in result.entities
        if str(root) in entity.qualified_name or temporary in entity.qualified_name
    ]
    if leaked:
        raise SystemExit(f"Code graph leaked provider workspace identity: {leaked}")
    invalid_paths = [
        entity.relative_path
        for entity in result.entities
        if entity.relative_path not in {"authorization.py", "payments.py"}
    ]
    if invalid_paths:
        raise SystemExit(f"Code graph escaped the ingested source set: {invalid_paths}")

    print(
        json.dumps(
            {
                "status": "passed",
                "provider": result.provider,
                "provider_version": result.provider_version,
                "entities": len(result.entities),
                "relationships": len(result.relationships),
                "diagnostics": adapter.diagnostics(),
            },
            sort_keys=True,
        )
    )
PY

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 - <<'PY'
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path.cwd()
errors: list[str] = []


def tracked_files() -> list[str]:
    payload = subprocess.check_output(["git", "ls-files", "-z"])
    return [item.decode() for item in payload.split(b"\0") if item]


tracked = tracked_files()
generated_roots = {
    ".logs",
    ".playwright-cli",
    ".nasus",
    "node_modules",
    "playwright-report",
    "test-results",
}
for name in tracked:
    parts = Path(name).parts
    if any(part in generated_roots for part in parts) or name.endswith((".pyc", ".pyo")):
        errors.append(f"generated runtime artifact is tracked: {name}")

for name in tracked:
    path = Path(name)
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        errors.append(f"private environment file is tracked: {name}")

env_example = ROOT / ".env.example"
assignments: list[str] = []
for raw_line in env_example.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key = line.split("=", 1)[0].strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        assignments.append(key)
for key, count in sorted(Counter(assignments).items()):
    if count > 1:
        errors.append(f".env.example defines {key} {count} times")

private_key_pattern = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}"
)
for name in tracked:
    path = ROOT / name
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        continue
    try:
        payload = path.read_bytes()
    except OSError:
        continue
    if private_key_pattern.search(payload):
        errors.append(f"probable private credential material is tracked: {name}")

if errors:
    raise SystemExit("Release hygiene failed:\n- " + "\n- ".join(errors))

print(
    "Release hygiene passed: no generated artifacts/private env files/private keys "
    "are tracked and .env.example has unique assignments."
)
PY

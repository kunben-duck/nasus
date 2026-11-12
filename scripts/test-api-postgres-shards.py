"""Run a complete backend suite in disjoint per-file PostgreSQL/MinIO shards."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
RUNNER = [sys.executable, str(ROOT / "scripts/test-api-postgres.py"), "--minio"]
NODE = re.compile(r"((?:apps/api/tests|tests)/[^:\r\n]+\.py)::.+")
COLLECTION = re.compile(r"^(\d+) tests? collected in [^\r\n]+$", re.MULTILINE)
OPERATOR_OPTIONS = {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD", "EXWEB_CANONICAL_HANDOFF_REPORT"}


def inventory(output):
    nodes = [line for line in output.splitlines() if NODE.fullmatch(line)]
    totals = COLLECTION.findall(output)
    if totals != [str(len(nodes))] or not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("backend collection is empty, incomplete, filtered, or duplicated")
    return Counter(node.split("::", 1)[0] for node in nodes)


def partitions(counts, workers):
    if not 2 <= workers <= 4 or len(counts) < workers:
        raise ValueError("need at least one independent test file per shard")
    groups = [Counter() for _ in range(workers)]
    totals = [0] * workers
    for filename in sorted(counts, key=lambda name: (-counts[name], name)):
        index = totals.index(min(totals))
        groups[index][filename] = counts[filename]
        totals[index] += counts[filename]
    return groups


def verify_junit(path, expected):
    cases = list(ElementTree.parse(path).iter("testcase"))
    actual = Counter(case.get("file") for case in cases)
    if actual != expected or any(case.find("error") is not None or case.find("failure") is not None for case in cases):
        raise ValueError("shard result differs from the collected file inventory or contains failures")


def run_shard(index, counts, directory, env):
    xml = directory / f"shard-{index}.xml"
    log = directory / f"shard-{index}.log"
    with log.open("x", encoding="utf-8") as stream:
        run = subprocess.run([*RUNNER, *sorted(counts), "-q", "-o", "junit_family=xunit1", "--junitxml", str(xml)],
            cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if run.returncode:
        raise RuntimeError(f"pytest/cleanup exited {run.returncode}; see {log}")
    verify_junit(xml, counts)
    return sum(counts.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(2, 5), required=True)
    parser.add_argument("suites", nargs="+")
    args = parser.parse_args()
    for suite in args.suites:
        resolved = (ROOT / suite).resolve()
        if not any(resolved.is_relative_to(ROOT / allowed) for allowed in ("apps/api/tests", "tests")) or not resolved.exists():
            parser.error("suite must be an existing test path inside this checkout")

    env = {key: value for key, value in os.environ.items() if key not in OPERATOR_OPTIONS}
    output = ROOT / "output/release-backend-shards"
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    print(f"Backend shard evidence: {directory}", flush=True)
    with (directory / "collection.log").open("x+", encoding="utf-8") as stream:
        run = subprocess.run([*RUNNER, *args.suites, "--collect-only", "-q"], cwd=ROOT, env=env,
            stdout=stream, stderr=subprocess.STDOUT, check=False)
        if run.returncode:
            raise SystemExit(f"Backend collection exited {run.returncode}; see {stream.name}")
        stream.seek(0)
        counts = inventory(stream.read())

    groups = partitions(counts, args.workers)
    print(f"Collected {sum(counts.values())} tests across {len(counts)} files; running {args.workers} isolated shards.", flush=True)
    total, failed = 0, False
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run_shard, index, group, directory, env): index for index, group in enumerate(groups, 1)}
        for done in as_completed(pending):
            index = pending[done]
            try:
                cases = done.result()
                total += cases
                print(f"Backend shard {index}: {cases} recorded cases; pytest and cleanup passed.", flush=True)
            except (OSError, RuntimeError, ValueError, ElementTree.ParseError) as error:
                print(f"Backend shard {index} failed: {error}", file=sys.stderr, flush=True)
                failed = True
    if failed or total != sum(counts.values()):
        raise SystemExit(f"Backend shards did not verify the full inventory; see {directory}")
    print(f"Verified all {total} collected backend tests across {args.workers} isolated shards.")


if __name__ == "__main__":
    main()

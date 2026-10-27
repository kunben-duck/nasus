from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.context_dependencies import QualityContextDependencyApplicationService
from apps.api.app.domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationImpactTooLarge
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope


HASH = snapshot_digest("fixture")


@pytest.fixture
def dependencies():
    calls = []
    selected = [("scope", "s"), ("generation", "g"), ("mapping", "m")]
    scopes = {"s": {"revision": {"project_id": "p", "revision_id": "s", "context_id": "c",
        "artifact_hash": HASH, "previous_revision_id": None}}}
    results = {"g": {"metadata": {"project_id": "p", "generation_id": "g", "scope_revision_id": "s", "artifact_hash": HASH},
        "result": {"proposal": {"cases": [{"case_id": "one", "steps": ["private fixture"]}], "coverage": {"passed": False}}}}}
    mappings = {"m": {"revision": {"project_id": "p", "revision_id": "m", "generation_id": "g", "artifact_hash": HASH,
        "generation_artifact_hash": HASH, "previous_revision_id": None}}}
    def reader(values, kind):
        def read(project, ident):
            calls.append((kind, ident))
            return values[ident]
        return SimpleNamespace(read=read)
    app = QualityContextDependencyApplicationService(SimpleNamespace(list=lambda *a: tuple(selected)),
        reader(scopes, "scope"), reader(results, "generation"), reader(mappings, "mapping"),
        SimpleNamespace(scope=lambda p: "scope", require_current=lambda s: None))
    return app, selected, scopes, results, mappings, calls


def test_quality_port_verifies_each_artifact_and_derives_case_and_coverage_nodes(dependencies):
    app, selected, _, _, _, calls = dependencies
    nodes = app.read("p", "c")
    assert len(nodes) == 5 and set(calls) == set(selected)
    assert {n.kind for n in nodes} == {"scope", "generation", "case", "coverage", "mapping"}
    original = nodes
    selected.append(("scope", "new"))
    assert app.read("p", "c", pinned=tuple(selected[:-1])) == original


@pytest.mark.parametrize("kind,field,value", [("scope", "context_id", "another"), ("scope", "project_id", "another"),
    ("generation", "scope_revision_id", "missing"), ("mapping", "generation_artifact_hash", snapshot_digest("wrong"))])
def test_cross_context_project_or_artifact_pins_fail_closed(dependencies, kind, field, value):
    app, _, scopes, results, mappings, _ = dependencies
    table = {"scope": scopes, "generation": results, "mapping": mappings}[kind]
    view = next(iter(table.values()))
    view["metadata" if kind == "generation" else "revision"][field] = value
    with pytest.raises(DerivationImpactIntegrityError):
        app.read("p", "c")


def test_duplicate_inventory_and_case_expansion_over_budget_are_not_truncated(dependencies):
    app, selected, _, results, _, calls = dependencies
    selected.append(selected[0])
    with pytest.raises(DerivationImpactIntegrityError):
        app.read("p", "c")
    assert not calls
    selected.pop()
    results["g"]["result"]["proposal"]["cases"] = [{"case_id": str(i)} for i in range(128)]
    with pytest.raises(DerivationImpactTooLarge):
        app.read("p", "c")


def test_inventory_failure_rechecks_original_access_before_capacity_diagnostics(dependencies):
    app, _, _, _, _, calls = dependencies
    revoked = []
    def inventory(*args):
        revoked.append(True)
        raise DerivationImpactTooLarge("private fixture count")
    def current(access):
        if revoked:
            raise StaleSourceAccessScope("fixture revocation")
    app.inventory.list = inventory
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.read("p", "c")
    assert not calls


@pytest.mark.parametrize("pinned", [None, [], (("scope", True),), (("scope", "s", "extra"),)])
def test_invalid_inventory_shape_cannot_reach_artifact_reads(dependencies, pinned):
    app, _, _, _, _, calls = dependencies
    app.inventory.list = lambda *args: pinned
    with pytest.raises(DerivationImpactIntegrityError):
        app.read("p", "c")
    assert not calls

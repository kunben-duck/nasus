"""Write authorization remains an application port, including fail-closed assembly."""
from copy import deepcopy

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.source_access import SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope
from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
from apps.api.tests.test_source_refresh import REQUEST, fixture


@pytest.mark.parametrize("selection", [None, source_refresh_selection(REQUEST)])
@pytest.mark.parametrize("fault", ["missing_port", "unavailable", "unknown_source", "foreign_scope", "changed_policy"])
def test_write_fails_closed_before_mutation_or_connector(selection, fault):
    v = fixture()
    before = deepcopy(v.sources)
    if fault == "missing_port":
        v.service._authorization = None
    elif fault == "unavailable":
        def unavailable(_):
            raise RuntimeError("private-policy-database:credentials")
        v.authorization.scope = unavailable
    elif fault == "changed_policy":
        def changed(_):
            raise StaleSourceAccessScope("private-policy-epoch")
        v.authorization.require_current = changed
    else:
        scope = SourceAccessSnapshot("other-project" if fault == "foreign_scope" else "project", 0, ()).for_actor("actor", "tester")
        v.authorization.scope = lambda _: scope
    with pytest.raises(PlatformApplicationError) as raised:
        v.invoke(selection)
    assert raised.value.code == ("source_access_unavailable" if fault in {"missing_port", "unavailable"} else "source_access_denied")
    assert raised.value.status_code == (503 if fault in {"missing_port", "unavailable"} else 403)
    assert "private" not in raised.value.message
    assert v.sources == before and v.events == []


def test_selected_refresh_does_not_require_access_to_unselected_sources():
    v = fixture()
    v.authorization.scope = lambda _: SourceAccessSnapshot("project", 0, (SourceBindingAccess("code", "code"),)).for_actor("actor", "tester")
    v.invoke(source_refresh_selection(REQUEST))
    assert [event for event in v.events if type(event) is tuple and event[0] == "ingest"] == [("ingest", "code")]


def test_whole_project_cannot_use_a_scope_that_only_allows_one_source():
    v = fixture()
    v.authorization.scope = lambda _: SourceAccessSnapshot("project", 0, (SourceBindingAccess("code", "code"),)).for_actor("actor", "tester")
    with pytest.raises(PlatformApplicationError, match="not authorized"):
        v.invoke(None)
    assert v.events == []


@pytest.mark.parametrize("fault", ["foreign_project", "duplicate_id"])
def test_whole_project_rejects_incoherent_projection_before_authorization(fault):
    v = fixture()
    if fault == "foreign_project":
        v.sources[0].project_id = "other-project"
    else:
        v.sources[1].id = v.sources[0].id
    with pytest.raises(ValueError, match="this project's"):
        v.invoke(None)
    assert v.events == []


@pytest.mark.parametrize("failure", [False, True])
def test_connector_revocation_stops_before_inventory_manifest_or_next_source(failure):
    v = fixture()
    acquire = v.service._source_ingestion.ingest

    def ingest(source):
        acquired = acquire(source)
        def changed(_):
            raise StaleSourceAccessScope("revoked during acquisition")
        v.authorization.require_current = changed
        if failure:
            raise OSError("private-connector-error")
        return acquired

    v.service._source_ingestion.ingest = ingest
    with pytest.raises(PlatformApplicationError, match="not authorized"):
        v.invoke(None)
    assert [event for event in v.events if type(event) is tuple and event[0] == "ingest"] == [("ingest", "code")]
    assert not any(type(event) is tuple and event[0] in {"manifest", "chunks"} for event in v.events)
    assert all(source.content_ref == "archive:" + source.id for source in v.sources)


def test_scope_is_rechecked_immediately_before_each_connector():
    v = fixture()
    checks = []

    def changed(scope):
        checks.append(scope)
        if len(checks) == 2:
            raise StaleSourceAccessScope("revoked after initial authorization")

    v.authorization.require_current = changed
    with pytest.raises(PlatformApplicationError, match="not authorized"):
        v.invoke(source_refresh_selection(REQUEST))
    assert len(checks) == 2
    assert not any(type(event) is tuple and event[0] == "ingest" for event in v.events)

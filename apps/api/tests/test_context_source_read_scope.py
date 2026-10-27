"""Verify scope delegation; actual source/authority checks use PG API tests."""
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.context_pack_sources import TestDesignContextSources as ContextSources
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_link_candidate_queries import Images


@pytest.mark.parametrize("nested", [False, True])
def test_context_compilation_reuses_only_an_enclosing_scope_and_checks_live_access(nested):
    images = Images()
    service = ContextSources(images, None, None)
    calls = []

    def prepare(request, *, pinned):
        assert images.snapshot_depth == 1
        calls.append((request, pinned))
        images.authorization.require_current("current-access")
        return {"fixed": pinned}

    service._prepare = prepare
    request, pin = SimpleNamespace(), {"historical": "explicit-protocol-pin"}
    if nested:
        with images.verified_read_session():
            assert service.prepare(request, pinned=pin) == {"fixed": pin}
            images.allowed = False
            with pytest.raises(SourceAccessDenied):
                service.prepare(request, pinned=pin)
            assert images.snapshot_entries == [1] and images.snapshot_depth == 1
    else:
        assert service.prepare(request, pinned=pin) == {"fixed": pin}
        images.allowed = False
        with pytest.raises(SourceAccessDenied):
            service.prepare(request, pinned=pin)
        assert images.snapshot_entries == [1, 1]
    assert calls == [(request, pin)] * 2 and images.snapshot_depth == 0

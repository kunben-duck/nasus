"""Application control-flow tests; native PG/archive safety is tested separately."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.context_pack_inputs import ContextCompileInput, preview_request
from apps.api.app.application.system_image.context_packs import ContextPackApplicationService
from apps.api.app.domain.system_image.context_pack import (
    ContextIndexChanged, ContextPackIntegrityError, ContextPublicationChanged, MandatoryContextTooLarge,
)
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope


DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def reader(monkeypatch):
    calls = []

    class Authorization:
        depth = 0
        epoch = 0

        @contextmanager
        def live_read_session(self):
            self.depth += 1
            calls.append("open")
            try:
                yield
            finally:
                self.depth -= 1
                calls.append("close")

        def scope(self, project_id):
            assert self.depth > 0 and project_id == "project"
            calls.append("scope")
            return self.epoch

        def require_current(self, scope):
            assert self.depth > 0
            calls.append("current")
            if scope != self.epoch:
                raise StaleSourceAccessScope("source access changed")

    authorization = Authorization()
    request = ContextCompileInput(project_id="project", image_revision_id="image",
        image_artifact_hash=DIGEST, expected_input_digest=DIGEST)
    metadata = {"artifact_hash": DIGEST}
    payload = {"input_digest": DIGEST, "request": request.model_dump(mode="json"),
        "context": {"required_constraints": [{"oracle": None}], "readiness": {"status": "blocked"}}}

    def verify(project_id, context_id):
        assert authorization.depth > 0 and (project_id, context_id) == ("project", "context")
        calls.append("verify")
        return deepcopy(metadata), deepcopy(payload), request

    def prepare(actual):
        assert authorization.depth > 0 and actual == preview_request(request)
        calls.append("prepare")
        return {"input_digest": DIGEST}

    def stale(project_id, context_id, artifact_hash):
        assert authorization.depth > 0 and (project_id, context_id, artifact_hash) == ("project", "context", DIGEST)
        calls.append("stale")
        return None

    service = ContextPackApplicationService(None, authorization, SimpleNamespace(stale_state=stale), None)
    monkeypatch.setattr(service, "_verify_stored", verify)
    monkeypatch.setattr(service, "_prepare", prepare)
    return service, authorization, calls, payload


def test_all_original_read_stages_share_scope_without_caching_the_next_request(reader):
    service, authorization, calls, payload = reader
    first = service.read("project", "context")
    assert first["context"] == payload["context"]
    assert first["current_use"] == {"stale": False, "generation_authorized": False, "reason": "draft_investigation_only"}
    assert calls == ["open", "scope", "verify", "prepare", "stale", "current", "close"]
    assert authorization.depth == 0
    assert service.read("project", "context") == first
    assert calls == ["open", "scope", "verify", "prepare", "stale", "current", "close"] * 2
    assert authorization.depth == 0


@pytest.mark.parametrize("stage", ["scope", "verify", "prepare", "stale", "current"])
def test_scope_closes_on_each_failed_original_stage_and_next_read_is_independent(reader, monkeypatch, stage):
    service, authorization, calls, _ = reader
    target, name = {"scope": (authorization, "scope"), "verify": (service, "_verify_stored"),
        "prepare": (service, "_prepare"), "stale": (service.repository, "stale_state"),
        "current": (authorization, "require_current")}[stage]
    failure = SourceAccessDenied("private source") if stage in {"scope", "current"} else ContextPackIntegrityError("invalid original")

    def fail(*args, **options):
        assert authorization.depth > 0
        raise failure

    with monkeypatch.context() as scoped:
        scoped.setattr(target, name, fail)
        with pytest.raises(type(failure)) as caught:
            service.read("project", "context")
    assert caught.value is failure and authorization.depth == 0 and calls[-1] == "close"
    assert service.read("project", "context")["current_use"]["stale"] is False
    assert authorization.depth == 0


@pytest.mark.parametrize("error,reason", [
    (MandatoryContextTooLarge("budget"), "current_mandatory_context_over_budget"),
    (ContextPublicationChanged("publication"), "published_image_head_changed"),
    (ContextIndexChanged("model"), "retrieval_model_configuration_changed"),
])
def test_historical_stale_reasons_and_final_reauthorization_are_preserved(reader, monkeypatch, error, reason):
    service, authorization, calls, payload = reader

    def changed(*args, **options):
        assert authorization.depth > 0
        raise error

    monkeypatch.setattr(service, "_prepare", changed)
    result = service.read("project", "context")
    assert result["context"] == payload["context"]
    assert result["current_use"] == {"stale": True, "generation_authorized": False, "reason": reason}
    assert calls[-3:] == ["stale", "current", "close"] and authorization.depth == 0


def test_revocation_during_replay_does_not_return_old_context_or_keep_scope(reader, monkeypatch):
    service, authorization, calls, _ = reader
    original = service._verify_stored

    def revoke(*args, **options):
        result = original(*args, **options)
        authorization.epoch += 1
        return result

    monkeypatch.setattr(service, "_verify_stored", revoke)
    with pytest.raises(StaleSourceAccessScope, match="source access changed"):
        service.read("project", "context")
    assert calls[-2:] == ["current", "close"] and authorization.depth == 0


def test_persisted_invalidation_still_wins_without_changing_historical_bytes(reader, monkeypatch):
    service, authorization, _, payload = reader
    monkeypatch.setattr(service.repository, "stale_state", lambda *args: {"invalidation_id": "invalidation"})
    result = service.read("project", "context")
    assert result["context"] == payload["context"]
    assert result["current_use"] == {"stale": True, "generation_authorized": False,
        "reason": "source_change_invalidated", "invalidation_id": "invalidation"}
    assert authorization.depth == 0

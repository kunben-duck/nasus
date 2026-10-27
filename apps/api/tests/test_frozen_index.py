import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.app.application.platform.model_execution_profiles import ModelExecutionProfileApplicationService
from apps.api.app.domain.system_image.retrieval_index import split_utf8, validate_vectors, fuse_ranks
from apps.api.app.infrastructure.llm.index_embedding import HTTPIndexEmbedding, IndexEmbeddingFailure
from apps.api.tests.test_semantic_link_model import saved_config


def model(**changes):
    service = ModelExecutionProfileApplicationService(
        SimpleNamespace(get_model_config_snapshot=lambda ident: (saved_config(route="embedding", **changes), "encrypted")),
        SimpleNamespace(decrypt_api_key=lambda encrypted: "secret-key"))
    return service.resolve("model", route="embedding")


def test_unicode_chunks_are_complete_and_bounded():
    source = "中文 😀 source\n" * 3000
    parts = split_utf8(source)
    assert "".join(parts) == source and all(0 < len(part.encode()) <= 4096 for part in parts)
    assert len(parts) > 1


@pytest.mark.parametrize("values", [[[0, 0]], [[True, 1]], [[float("nan"), 1]], [[float("inf"), 1]],
    [[1e90, 0]], [[1e-90, 0]], [["1", 2]], [[]], [], [[1, 0], [1]]])
def test_vectors_reject_invalid_dimensions_nan_zero_and_overflow(values):
    with pytest.raises(ValueError):
        validate_vectors(values, max(1, len(values)))


def test_native_embedding_reorders_by_provider_index_and_uses_pinned_secret():
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url == "https://models.example/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer secret-key"
        assert json.loads(request.content)["input"] == ["代码", "test"]
        return httpx.Response(200, json={"model": "test-model", "data": [
            {"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}], "usage": {"prompt_tokens": 12}})
    result = asyncio.run(HTTPIndexEmbedding(transport=httpx.MockTransport(handle)).embed(("代码", "test"), model()))
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert result.input_tokens == 12 and result.usage_source == "provider" and len(calls) == 1


@pytest.mark.parametrize("failure", ["duplicate", "missing", "model", "dimension", "nan", "zero", "redirect", "error", "oversize"])
def test_native_failure_is_redacted_and_never_retried(failure):
    calls = []
    def handle(request):
        calls.append(request)
        if failure == "redirect":
            return httpx.Response(307, headers={"location": "https://secret.example"})
        if failure == "error":
            return httpx.Response(500, text="secret-key")
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * (8 * 1024 * 1024 + 1))
        payload = {"model": "test-model", "data": [{"index": 0, "embedding": [1, 0]}, {"index": 1, "embedding": [0, 1]}]}
        if failure == "duplicate":
            payload["data"][1]["index"] = 0
        elif failure == "missing":
            payload["data"].pop()
        elif failure == "model":
            payload["model"] = "other"
        elif failure == "dimension":
            payload["data"][1]["embedding"] = [1]
        elif failure == "nan":
            return httpx.Response(200, content=b'{"data":[{"index":0,"embedding":[NaN,1]},{"index":1,"embedding":[1,0]}]}')
        elif failure == "zero":
            payload["data"][1]["embedding"] = [0, 0]
        return httpx.Response(200, json=payload)
    with pytest.raises(IndexEmbeddingFailure) as error:
        asyncio.run(HTTPIndexEmbedding(transport=httpx.MockTransport(handle)).embed(("a", "b"), model()))
    assert len(calls) == 1 and "secret" not in str(error.value)


def test_ranking_ties_are_stable_and_profiles_cannot_mix():
    assert fuse_ranks(["a", "b"], ["b", "a"], limit=2)[0][0] == "a"
    assert model().binding != model(updated_at="new-config").binding
    for changes in ({"provider_kind": "anthropic"}, {"provider_kind": "gemini"}, {"last_test_result": {"ok": False}}):
        with pytest.raises(ValueError):
            model(**changes)

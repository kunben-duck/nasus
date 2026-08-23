from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.system_image.model_route_policy import (
    SystemImageModelRouteUnavailableError,
    require_live_system_image_result,
)


def test_development_fallback_result_remains_explicitly_available() -> None:
    result = SimpleNamespace(
        mode="fallback",
        provider="mock",
        model_name="mock-hash-embedding",
        reason="development provider is unavailable",
    )

    assert result.mode == "fallback"


def test_production_embedding_route_rejects_fallback_result() -> None:
    result = SimpleNamespace(
        mode="fallback",
        provider="mock",
        model_name="mock-hash-embedding",
        reason="provider timeout",
    )

    with pytest.raises(
        SystemImageModelRouteUnavailableError,
        match="embedding route must be live in production",
    ):
        require_live_system_image_result("embedding", result)


def test_production_rerank_route_rejects_fallback_result() -> None:
    result = SimpleNamespace(
        mode="fallback",
        provider="mock",
        model_name="rule-based-fusion",
        reason="provider returned 503",
    )

    with pytest.raises(
        SystemImageModelRouteUnavailableError,
        match="rerank route must be live in production",
    ):
        require_live_system_image_result("rerank", result)


def test_production_route_accepts_live_result_without_translation() -> None:
    result = SimpleNamespace(
        mode="live",
        provider="openai_compatible",
        model_name="production-model",
        reason="provider_success",
    )

    assert require_live_system_image_result("embedding", result) is result

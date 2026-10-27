from __future__ import annotations

import os
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .application.platform.actor_context import bind_actor, reset_actor
from .application.platform.errors import PlatformApplicationError
from .application.platform.request_rate_limits import RequestRateLimitApplicationService
from .interface.http.auth import authenticate_request
from .interface.http.request_context import (
    REQUEST_ID_HEADER,
    bind_request_id,
    error_envelope,
    reset_request_id,
    resolve_request_id,
)
from .interface.http.request_limits import request_limit_target
from .infrastructure.config.rate_limit_config import RateLimitConfig
from .infrastructure.config.runtime_config import validate_runtime_configuration
from .infrastructure.persistence.database import SessionLocal
from .infrastructure.platform.http_metrics import HttpMetrics
from .infrastructure.platform.operational_metrics import SQLAlchemyOperationalMetricsCollector
from .infrastructure.platform.operator_identity import SQLAlchemyConfiguredIdentityReader, SQLAlchemyOperatorIdentityBootstrap
from .infrastructure.platform.request_rate_limiter import SQLAlchemyFixedWindowRateLimiter


def create_app() -> FastAPI:
    validate_runtime_configuration()

    from .bootstrap import get_application_container
    from .interface.http.routers import agent, conversations, health, identity, platform, projects, source_evidence, code_analysis, image_revisions, build_plans, source_documents, acceptance_specifications, context_packs

    container = get_application_container()
    if container.auth_config.disabled or container.auth_config.bearer_token:
        SQLAlchemyOperatorIdentityBootstrap().ensure(container.auth_config.user())
    configured_identities = SQLAlchemyConfiguredIdentityReader()
    app = FastAPI(title="Nasus API", version="0.1.0")
    app.state.container = container
    # Mutable aliases are retained only as explicit test override seams.
    app.state.auth_config = container.auth_config
    app.state.readiness = container.readiness
    app.state.http_metrics = HttpMetrics(
        (SQLAlchemyOperationalMetricsCollector(SessionLocal),)
    )
    app.state.rate_limit_config = RateLimitConfig.from_env()
    app.state.request_rate_limiter = RequestRateLimitApplicationService(
        SQLAlchemyFixedWindowRateLimiter(SessionLocal)
    )

    @app.exception_handler(PlatformApplicationError)
    async def platform_application_error_handler(
        request: Request,
        exc: PlatformApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                request_id=resolve_request_id(request),
                code=exc.code,
                message=exc.message,
            ),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.getenv("NASUS_CORS_ALLOW_ORIGINS", "*").split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def platform_request_middleware(request: Request, call_next):
        request_id = resolve_request_id(request)
        request_token = bind_request_id(request_id)
        metrics = request.app.state.http_metrics
        metrics.in_progress.inc()
        started_at = perf_counter()
        response = None
        user = None
        status_code = 500
        try:
            auth_result = authenticate_request(
                request,
                request.app.state.auth_config,
                request.app.state.container.platform.authenticate_token,
                configured_identities.authenticate,
            )
            if isinstance(auth_result, JSONResponse):
                response = auth_result
            else:
                user = auth_result
                request.state.user = user
                response = _enforce_request_limit(request, user)
                if response is None:
                    actor_token = bind_actor(user, request_id=request_id)
                    try:
                        response = await call_next(request)
                    finally:
                        reset_actor(actor_token)
            decision = getattr(request.state, "rate_limit_decision", None)
            if decision is not None:
                response.headers["X-RateLimit-Limit"] = str(decision.limit)
                response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
                response.headers["X-RateLimit-Reset"] = str(decision.reset_at_epoch)
                response.headers["X-RateLimit-Scope"] = decision.scope
            response.headers[REQUEST_ID_HEADER] = request_id
            status_code = response.status_code
            return response
        finally:
            duration = perf_counter() - started_at
            metrics.in_progress.dec()
            metrics.observe(
                request_id=request_id,
                method=request.method,
                route=metrics.route_label(request),
                path=request.url.path,
                status_code=status_code,
                duration_seconds=duration,
                user_id=getattr(user, "id", None),
            )
            reset_request_id(request_token)

    app.include_router(health.router)
    app.include_router(platform.router)
    app.include_router(identity.router)
    app.include_router(projects.router)
    app.include_router(source_evidence.router)
    app.include_router(code_analysis.router)
    from .interface.http.routers import code_indexes
    app.include_router(code_indexes.router)
    from .interface.http.routers import source_deltas
    app.include_router(source_deltas.router)
    from .interface.http.routers import context_change_impact
    app.include_router(context_change_impact.router)
    app.include_router(source_documents.router)
    app.include_router(image_revisions.router)
    app.include_router(acceptance_specifications.router)
    from .interface.http.routers import business_rules
    app.include_router(business_rules.router)
    from .interface.http.routers import test_design_scopes
    app.include_router(test_design_scopes.router)
    from .interface.http.routers import test_design_mappings
    app.include_router(test_design_mappings.router)
    from .interface.http.routers import automation_inputs
    app.include_router(automation_inputs.router)
    from .interface.http.routers import case_approvals
    app.include_router(case_approvals.router)
    from .interface.http.routers import automation_scripts
    app.include_router(automation_scripts.router)
    from .interface.http.routers import run_plans
    app.include_router(run_plans.router)
    from .interface.http.routers import test_design_review_queries
    app.include_router(test_design_review_queries.router)
    app.include_router(context_packs.router)
    from .interface.http.routers import image_publications
    app.include_router(image_publications.router)
    from .interface.http.routers import frozen_indexes
    app.include_router(frozen_indexes.router)
    app.include_router(build_plans.router)
    app.include_router(conversations.router)
    app.include_router(agent.router)
    return app


def _enforce_request_limit(request: Request, user) -> JSONResponse | None:
    config: RateLimitConfig = request.app.state.rate_limit_config
    if not config.enabled:
        return None
    target = request_limit_target(request, user)
    if target is None:
        return None
    try:
        decision = request.app.state.request_rate_limiter.consume(
            scope=target.scope,
            principal=target.principal,
            limit=config.limit_for(target.scope),
            window_seconds=config.window_seconds,
        )
    except Exception:
        return JSONResponse(
            status_code=503,
            content=error_envelope(
                request_id=resolve_request_id(request),
                code="rate_limiter_unavailable",
                message="The shared request limiter is unavailable.",
            ),
        )

    request.state.rate_limit_decision = decision
    if decision.allowed:
        return None
    request.app.state.http_metrics.rate_limit_rejections.labels(target.scope).inc()
    return JSONResponse(
        status_code=429,
        content=error_envelope(
            request_id=resolve_request_id(request),
            code="rate_limit_exceeded",
            message="Request rate limit exceeded.",
            retry_after=decision.retry_after_seconds,
            details={"scope": decision.scope},
        ),
        headers={
            "Retry-After": str(decision.retry_after_seconds),
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_at_epoch),
            "X-RateLimit-Scope": decision.scope,
        },
    )

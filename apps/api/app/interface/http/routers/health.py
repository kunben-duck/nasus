from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from ..dependencies import OperationalMetricsApp, ReadinessApp

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(readiness: ReadinessApp) -> JSONResponse:
    report = readiness.check()
    return JSONResponse(
        status_code=200 if report.ready else 503,
        content=report.to_dict(),
    )


@router.get("/metrics", include_in_schema=False)
def metrics(metrics_exporter: OperationalMetricsApp) -> Response:
    return Response(
        content=metrics_exporter.render(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )

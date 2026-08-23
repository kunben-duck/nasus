from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from time import perf_counter, time
from typing import Any

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from ..persistence.db_models import (
    AgentGoalRecord,
    AgentSwarmRunRecord,
    ApprovalRecord,
    ConversationMessageRecord,
    ConversationRecord,
    FailureReportRecord,
    LLMCallRecord,
    MergedResolutionRecord,
    RawAssetRecord,
    ReleaseReadinessRecord,
    RunRecord,
    ToolInvocationRecord,
)


LOGGER = logging.getLogger("nasus.operational_metrics")


class SQLAlchemyOperationalMetricsCollector:
    """Export durable bounded-context state without instrumenting domain code.

    The values are gauges because retention, archival, and project deletion can
    legitimately decrease them. Labels are restricted to platform-owned enums;
    project IDs, tool IDs, model names, and other unbounded values are never
    exposed as Prometheus labels.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def collect(self) -> Iterable[GaugeMetricFamily]:
        started_at = perf_counter()
        try:
            with self._session_factory() as session:
                metrics = [
                    self._status_metric(
                        session,
                        "nasus_conversations",
                        "Durable conversation sessions by lifecycle status.",
                        ConversationRecord.status,
                    ),
                    self._two_label_metric(
                        session,
                        "nasus_conversation_messages",
                        "Durable conversation messages by role and status.",
                        ("role", ConversationMessageRecord.role),
                        ("status", ConversationMessageRecord.status),
                    ),
                    self._status_metric(
                        session,
                        "nasus_agent_goals",
                        "Durable Agent goals by lifecycle status.",
                        AgentGoalRecord.status,
                    ),
                    self._status_metric(
                        session,
                        "nasus_agent_swarm_runs",
                        "Durable Agent swarm runs by lifecycle status.",
                        AgentSwarmRunRecord.status,
                    ),
                    self._status_metric(
                        session,
                        "nasus_tool_invocations",
                        "Durable tool invocations by lifecycle status.",
                        ToolInvocationRecord.status,
                    ),
                    self._status_metric(
                        session,
                        "nasus_quality_runs",
                        "Durable quality execution runs by lifecycle status.",
                        RunRecord.status,
                    ),
                    self._status_metric(
                        session,
                        "nasus_approvals",
                        "Durable governance approvals by lifecycle status.",
                        ApprovalRecord.status,
                    ),
                    self._status_metric(
                        session,
                        "nasus_merge_resolutions",
                        "Durable structured merge resolutions by lifecycle status.",
                        MergedResolutionRecord.status,
                    ),
                    self._two_label_metric(
                        session,
                        "nasus_raw_assets",
                        "Registered source assets by source type and ingestion status.",
                        ("source_type", RawAssetRecord.source_type),
                        ("status", RawAssetRecord.ingestion_status),
                    ),
                    self._two_label_metric(
                        session,
                        "nasus_failure_reports",
                        "Failure reports by lifecycle status and human fallback flag.",
                        ("status", FailureReportRecord.status),
                        ("fallback_to_human", FailureReportRecord.fallback_to_human),
                    ),
                    self._status_metric(
                        session,
                        "nasus_release_readiness",
                        "Version release-readiness records by lifecycle status.",
                        ReleaseReadinessRecord.status,
                    ),
                    self._llm_call_metric(session),
                    self._llm_token_metric(session),
                    self._scalar_metric(
                        "nasus_agent_goal_budget_exhaustions",
                        "Agent goals stopped by a configured runtime budget.",
                        session.scalar(
                            select(func.count(AgentGoalRecord.id)).where(
                                AgentGoalRecord.budget_exhausted_reason.is_not(None)
                            )
                        ),
                    ),
                    self._scalar_metric(
                        "nasus_repeated_failure_fingerprints",
                        "Failure fingerprints observed more than once.",
                        session.scalar(
                            select(func.count())
                            .select_from(
                                select(FailureReportRecord.failure_fingerprint)
                                .group_by(FailureReportRecord.failure_fingerprint)
                                .having(func.count(FailureReportRecord.id) > 1)
                                .subquery()
                            )
                        ),
                    ),
                ]
        except Exception as exc:
            LOGGER.error(
                json.dumps(
                    {
                        "event": "operational_metrics.snapshot.failed",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            yield self._snapshot_up(0)
            yield self._snapshot_duration(perf_counter() - started_at)
            return

        yield self._snapshot_up(1)
        yield self._snapshot_duration(perf_counter() - started_at)
        timestamp = GaugeMetricFamily(
            "nasus_operational_snapshot_timestamp_seconds",
            "Unix timestamp of the latest successful operational snapshot.",
        )
        timestamp.add_metric([], time())
        yield timestamp
        yield from metrics

    @staticmethod
    def _status_metric(session: Any, name: str, documentation: str, column: Any) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(name, documentation, labels=["status"])
        rows = session.execute(
            select(column, func.count()).group_by(column).order_by(column)
        ).all()
        for status, count in rows:
            metric.add_metric([SQLAlchemyOperationalMetricsCollector._label(status)], int(count))
        return metric

    @staticmethod
    def _two_label_metric(
        session: Any,
        name: str,
        documentation: str,
        first: tuple[str, Any],
        second: tuple[str, Any],
    ) -> GaugeMetricFamily:
        first_name, first_column = first
        second_name, second_column = second
        metric = GaugeMetricFamily(name, documentation, labels=[first_name, second_name])
        rows = session.execute(
            select(first_column, second_column, func.count())
            .group_by(first_column, second_column)
            .order_by(first_column, second_column)
        ).all()
        for first_value, second_value, count in rows:
            metric.add_metric(
                [
                    SQLAlchemyOperationalMetricsCollector._label(first_value),
                    SQLAlchemyOperationalMetricsCollector._label(second_value),
                ],
                int(count),
            )
        return metric

    @staticmethod
    def _llm_call_metric(session: Any) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(
            "nasus_llm_calls",
            "Audited model calls by route, outcome, and runtime mode.",
            labels=["route", "outcome", "runtime_mode"],
        )
        rows = session.execute(
            select(
                LLMCallRecord.route,
                LLMCallRecord.outcome,
                LLMCallRecord.runtime_mode,
                func.count(),
            )
            .group_by(
                LLMCallRecord.route,
                LLMCallRecord.outcome,
                LLMCallRecord.runtime_mode,
            )
            .order_by(
                LLMCallRecord.route,
                LLMCallRecord.outcome,
                LLMCallRecord.runtime_mode,
            )
        ).all()
        for route, outcome, runtime_mode, count in rows:
            metric.add_metric(
                [
                    SQLAlchemyOperationalMetricsCollector._label(route),
                    SQLAlchemyOperationalMetricsCollector._label(outcome),
                    SQLAlchemyOperationalMetricsCollector._label(runtime_mode),
                ],
                int(count),
            )
        return metric

    @staticmethod
    def _llm_token_metric(session: Any) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(
            "nasus_llm_tokens",
            "Audited model token usage by route and direction.",
            labels=["route", "direction"],
        )
        rows = session.execute(
            select(
                LLMCallRecord.route,
                func.coalesce(func.sum(LLMCallRecord.input_token_count), 0),
                func.coalesce(func.sum(LLMCallRecord.output_token_count), 0),
            )
            .group_by(LLMCallRecord.route)
            .order_by(LLMCallRecord.route)
        ).all()
        for route, input_tokens, output_tokens in rows:
            route_label = SQLAlchemyOperationalMetricsCollector._label(route)
            metric.add_metric([route_label, "input"], int(input_tokens))
            metric.add_metric([route_label, "output"], int(output_tokens))
        return metric

    @staticmethod
    def _scalar_metric(name: str, documentation: str, value: Any) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(name, documentation)
        metric.add_metric([], int(value or 0))
        return metric

    @staticmethod
    def _snapshot_up(value: int) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(
            "nasus_operational_snapshot_up",
            "Whether durable operational facts were collected successfully.",
        )
        metric.add_metric([], value)
        return metric

    @staticmethod
    def _snapshot_duration(value: float) -> GaugeMetricFamily:
        metric = GaugeMetricFamily(
            "nasus_operational_snapshot_duration_seconds",
            "Duration of the latest durable operational snapshot.",
        )
        metric.add_metric([], value)
        return metric

    @staticmethod
    def _label(value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)


__all__ = ["SQLAlchemyOperationalMetricsCollector"]

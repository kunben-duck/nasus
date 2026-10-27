"""Fixed code-to-action evidence through replaceable ports, never dispatch."""
from contextlib import nullcontext
from typing import Literal, Protocol

from pydantic import Field, StrictInt, model_validator

from .test_design_output import Digest, GenerationValue, Id
from ...domain.quality_loop.http_locator_evidence import (
    LOCATOR_STATES, compile_http_locator_evidence,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError


RUN_PLAN_LOCATOR_QUERY_TOOL = "query.quality.run_plan_locators"


class RunPlanLocatorQuery(GenerationValue):
    project_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest


class LocatorSummary(GenerationValue):
    locator_count: StrictInt = Field(ge=0, le=51200)
    static_match: StrictInt = Field(ge=0, le=51200)
    ambiguous: StrictInt = Field(ge=0, le=51200)
    unresolved: StrictInt = Field(ge=0, le=51200)
    not_found: StrictInt = Field(ge=0, le=51200)
    unsupported: StrictInt = Field(ge=0, le=51200)

    @model_validator(mode="after")
    def complete_roster(self):
        if self.locator_count != sum(getattr(self, state) for state in LOCATOR_STATES):
            raise ValueError("locator summary must retain its complete denominator")
        return self


class RunPlanLocatorReceipt(GenerationValue):
    schema_version: Literal["nasus.run-plan-locator-receipt.v1"] = Field(alias="schema")
    query: RunPlanLocatorQuery
    policy: Literal["nasus.http-locator-static-match.v1", "nasus.http-locator-static-match.v2"]
    plan_digest: Digest
    image_revision_id: Id
    image_artifact_hash: Digest
    inventory_hash: Digest
    report_hash: Digest
    summary: LocatorSummary
    historical_not_live: Literal[True]
    durable_locator_evidence_verified: Literal[False]
    runtime_locators_verified: Literal[False]
    fixtures_verified: Literal[False]
    execution_authorized: Literal[False]
    business_coverage_verified: Literal[False]
    automated_count: StrictInt = Field(ge=0, le=0)
    executed_on_target_count: StrictInt = Field(ge=0, le=0)
    passed_count: StrictInt = Field(ge=0, le=0)

    @model_validator(mode="before")
    @classmethod
    def exact_flags(cls, value):
        if type(value) is not dict or any(type(value.get(key)) is not bool for key in (
                "historical_not_live", "durable_locator_evidence_verified", "runtime_locators_verified",
                "fixtures_verified", "execution_authorized", "business_coverage_verified")):
            raise ValueError("static locator flags must be exact booleans")
        return value


class HttpLocatorInventoryPort(Protocol):
    def inspect(self, plan, *, require_access): ...
    def verify(self, plan, inventory, *, require_access): ...


class RunPlanLocatorApplicationService:
    def __init__(self, plans, authorization, inventory: HttpLocatorInventoryPort):
        self.plans, self.authorization, self.inventory = plans, authorization, inventory

    def _inputs(self, query):
        saved = self.plans.read(query.project_id, query.run_plan_id)
        metadata = saved["metadata"]
        if (metadata["project_id"] != query.project_id or metadata["run_plan_id"] != query.run_plan_id
                or metadata["artifact_hash"] != query.run_plan_artifact_hash):
            raise RunPlanIntegrityError("locator query differs from the original saved plan")
        return saved["artifact"]["plan"]

    def _session(self):
        operation = getattr(self.plans, "verified_read_session", None)
        return operation() if operation else nullcontext()

    def require_receipt_inputs_access(self, query):
        self.require_receipt_inputs_access_many((query,))

    def require_receipt_inputs_access_many(self, queries):
        if not 1 <= len(queries) <= 128 or any(not isinstance(query, RunPlanLocatorQuery) for query in queries):
            raise RunPlanIntegrityError("locator history requires a bounded original query roster")
        accesses = {query.project_id: self.authorization.scope(query.project_id) for query in queries}
        with self._session():
            for query in queries:
                self._inputs(query)
        for access in accesses.values():
            self.authorization.require_current(access)

    @staticmethod
    def _receipt(query, plan, report):
        return RunPlanLocatorReceipt.model_validate({"schema": "nasus.run-plan-locator-receipt.v1",
            "query": query.model_dump(mode="json"), "policy": report["policy"], "plan_digest": plan["plan_digest"],
            "image_revision_id": plan["source_pin"]["image_revision_id"],
            "image_artifact_hash": plan["source_pin"]["image_artifact_hash"],
            "inventory_hash": report["inventory"]["inventory_hash"], "report_hash": report["report_hash"],
            "summary": report["summary"], "historical_not_live": True, "durable_locator_evidence_verified": False,
            "runtime_locators_verified": False, "fixtures_verified": False, "execution_authorized": False,
            "business_coverage_verified": False, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
        }).model_dump(mode="json", by_alias=True)

    def inspect(self, query: RunPlanLocatorQuery):
        query = RunPlanLocatorQuery.model_validate(query.model_dump(mode="json"))
        access = self.authorization.scope(query.project_id)
        current = lambda: self.authorization.require_current(access)
        with self._session():
            plan = self._inputs(query)
            try:
                inventory = self.inventory.inspect(plan, require_access=current)
            except ValueError as exc:
                raise RunPlanIntegrityError("original frozen locator source bytes cannot be verified") from exc
            report = compile_http_locator_evidence(plan, inventory)
            current()
        return {"receipt": self._receipt(query, plan, report), "report": report}

    def authorize_historical_receipt(self, query, value):
        return self.authorize_historical_receipts(((query, value),))[0]

    def authorize_historical_receipts(self, values):
        if not 1 <= len(values) <= 128:
            raise RunPlanIntegrityError("locator history exceeds its original cohort bound")
        accesses, results = {}, []
        with self._session():
            for query, value in values:
                if (not isinstance(query, RunPlanLocatorQuery) or type(value) is not dict
                        or set(value) != {"receipt", "report"}):
                    raise RunPlanIntegrityError("locator history cannot be rebound")
                receipt = RunPlanLocatorReceipt.model_validate(value["receipt"])
                if receipt.query != query:
                    raise RunPlanIntegrityError("locator history original query differs")
                if query.project_id not in accesses:
                    accesses[query.project_id] = self.authorization.scope(query.project_id)
                plan = self._inputs(query)
                report = compile_http_locator_evidence(plan, value["report"]["inventory"])
                if value["report"] != report or value["receipt"] != self._receipt(query, plan, report):
                    raise RunPlanIntegrityError("locator original evidence or action roster differs")
                results.append(value)
        for access in accesses.values():
            self.authorization.require_current(access)
        return results

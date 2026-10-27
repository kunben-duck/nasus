"""Confirmed native script drafts, with durable no-resend budget reservations."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import time
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from .automation_script_inputs import (SCRIPT_REPLY_SCHEMA, SCRIPT_RESULT_SCHEMA, SCRIPT_RESERVATION_SCHEMA, SCRIPT_TOOL, ScriptHistoryQuery,
    ScriptExecutionConsent, ScriptExecutionRequest, ScriptExecutionSelection, script_messages, validate_script_output)
from .generation_budget import GenerationBudgetInvalid, GenerationModelPolicy, reserve_generation_budget, verify_generation_usage
from .generation_executor import GenerationNativeModelPort, GenerationOutcomeUnknown
from .generation_execution_inputs import GENERATION_TIMEOUT_SECONDS
from .test_design_results import TestDesignResultIntegrityError, response_digest
from .automation_inputs import AutomationInputSelection
from ...domain.platform.llm_call import LLMCall
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.automation_input import AutomationInputChanged, AutomationInputInvalid
from ...domain.quality_loop.test_design_mapping import TestDesignMappingChanged
from ...domain.quality_loop.test_design_scope import TestDesignScopeChanged
from ...domain.quality_loop.case_approval import CaseApprovalChanged, CaseApprovalIntegrityError
from ...domain.quality_loop.automation_case_admission import verify_automation_case_admission


class AutomationScriptRepositoryPort(Protocol):
    def get(self, project_id, invocation_id): ...
    def reserve(self, request, payload, *, require_current): ...
    def record_reply(self, request, payload, ref, digest, call, *, require_current): ...
    def record_failure(self, request, invocation_id, call): ...
    def record_result(self, request, payload, ref, digest, *, require_current): ...
    def result(self, project_id, script_revision_id): ...
    def history(self, query): ...


class AutomationSourceInventoryPort(Protocol):
    def automation_bindings(self, prepared): ...


class AutomationCaseAdmissionPort(Protocol):
    def read(self, project_id, revision_id): ...
    def resolve(self, project_id, revision_id, artifact_hash, prepared): ...
    def read_with_inputs(self, project_id, revision_id): ...


class AutomationScriptGenerationApplicationService:
    def __init__(self, inputs, profiles, policies, authorization, sources: AutomationSourceInventoryPort,
                 provider: GenerationNativeModelPort, repository: AutomationScriptRepositoryPort, replies, results,
                 *, admissions: AutomationCaseAdmissionPort = None):
        self.inputs, self.profiles, self.policies, self.authorization = inputs, profiles, policies, authorization
        self.sources, self.provider, self.repository, self.replies, self.results = sources, provider, repository, replies, results
        self.admissions = admissions

    def _admission(self, selection, prepared, *, historical=False):
        if selection.case_approval_revision_id is None or self.admissions is None:
            raise CaseApprovalChanged("independently approve the exact cases before new script generation")
        if historical:
            value = self.admissions.read(selection.project_id, selection.case_approval_revision_id)
        else:
            value = self.admissions.resolve(selection.project_id, selection.case_approval_revision_id,
                selection.case_approval_artifact_hash, prepared)
        return verify_automation_case_admission(prepared, value, selection.case_approval_revision_id,
            selection.case_approval_artifact_hash, current=not historical)

    def _admission_input(self, request, *, current=False):
        value, historical, live = self.admissions.read_with_inputs(request.project_id, request.case_approval_revision_id)
        if current and value.get("current_use", {}).get("case_admission_current") is not True:
            raise CaseApprovalChanged("case admission was withdrawn, superseded or lost current authority")
        prepared = live if current else historical
        if not isinstance(prepared, dict):
            raise CaseApprovalIntegrityError("case admission must return its complete verified input")
        verify_automation_case_admission(prepared, value, request.case_approval_revision_id,
            request.case_approval_artifact_hash, current=current)
        selection = request.selection()
        if (prepared["project_id"] != selection.project_id
                or prepared["mapping_pin"]["revision_id"] != selection.mapping_revision_id
                or prepared["mapping_pin"]["artifact_hash"] != selection.mapping_artifact_hash
                or prepared["selected_case_ids"] != sorted(selection.case_ids)):
            raise CaseApprovalIntegrityError("case admission input must match the original script selection")
        return prepared

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("automation model egress requires a project administrator")
        return access

    def _prepare(self, selection):
        selection = ScriptExecutionSelection.model_validate(selection.model_dump(mode="json"))
        access = self._access(selection.project_id)
        prepared = self.inputs.prepare(selection.selection())
        admission = self._admission(selection, prepared)
        model = self.profiles.resolve(selection.model_config_id, route="chat")
        counter = self.policies.resolve(model.binding)
        sources = self.sources.automation_bindings(prepared)
        for ident in sources:
            access.require_binding(ident)
        system, content = script_messages(prepared, http_protocol=selection.selected_http_protocol())
        policy = counter.policy.model_dump(mode="json")
        reservation = reserve_generation_budget(counter.policy, selection.budget, [counter.count(system, content)])
        plan = {"schema": "nasus.automation-call-plan.v2", "input_digest": prepared["input_digest"],
            "case_approval_pin": admission,
            "model_binding": asdict(model.binding), "policy": policy, "source_binding_ids": sources,
            "source_scope_digest": access.fingerprint, "budget": selection.budget.model_dump(mode="json"),
            "reservation": reservation, "messages_hash": acceptance_digest([system, content]),
            "timeout_seconds": GENERATION_TIMEOUT_SECONDS, "call_count": 1}
        execution = ScriptExecutionConsent(policy_digest=acceptance_digest(policy), plan_digest=acceptance_digest(plan),
            source_binding_ids=sources, source_scope_digest=access.fingerprint, budget=selection.budget)
        request = ScriptExecutionRequest(**selection.model_dump(mode="json"), input_digest=prepared["input_digest"],
            model_config_digest=model.binding.config_digest, execution=execution)
        self.authorization.require_current(access)
        return access, prepared, model, counter.policy, reservation, request

    def preview(self, selection):
        _, prepared, model, policy, reservation, request = self._prepare(selection)
        return {"request": request.model_dump(mode="json"), "provider": model.binding.provider,
            "model_name": model.binding.model_name, "destination": model.binding.base_url,
            "policy": policy.model_dump(mode="json"), "reservation": reservation, "call_count": 1,
            "input_bytes": len(script_messages(prepared, http_protocol=request.selected_http_protocol())[1].encode()), "timeout_seconds": GENERATION_TIMEOUT_SECONDS,
            "generation_authorized": False, "execution_authorized": False,
            "remaining_gates": ["fresh_user_confirmation", "durable_call_reservation", "independent_script_review", "immutable_run_plan"]}

    def history(self, query: ScriptHistoryQuery):
        query = ScriptHistoryQuery.model_validate(query.model_dump(mode="json"))
        access = self.authorization.scope(query.project_id)
        mapping = self.inputs.mappings.read(query.project_id, query.mapping_revision_id)
        if mapping["revision"]["artifact_hash"] != query.mapping_artifact_hash:
            raise TestDesignResultIntegrityError("automation history mapping pin mismatch")
        if mapping["revision"]["status"] != "reviewed" or not (mapping.get("assessment") or {}).get("accepted_case_ids"):
            raise AutomationInputInvalid("automation history requires an original reviewed mapping")
        # Replay the complete original input even for an empty page. Listing
        # metadata must not bypass source access or reveal a revoked count.
        prepared = self.inputs.replay(AutomationInputSelection(project_id=query.project_id,
            mapping_revision_id=query.mapping_revision_id, mapping_artifact_hash=query.mapping_artifact_hash,
            case_ids=tuple(mapping["assessment"]["accepted_case_ids"])))
        candidates = self.repository.history(query)
        items = []
        for candidate in candidates:
            stored = self.repository.get(query.project_id, candidate["invocation_id"])
            result = stored["result"] if stored else None
            if candidate["status"] == "completed" and not result:
                raise TestDesignResultIntegrityError("completed automation command lacks its draft")
            if result:
                draft = self.read(query.project_id, result["script_revision_id"])
                if (draft["result"]["prepared"]["mapping_pin"] != prepared["mapping_pin"]
                        or draft["result"]["prepared"]["generation_pin"] != prepared["generation_pin"]):
                    raise TestDesignResultIntegrityError("automation history derivation mismatch")
            reserved, replied = stored is not None, bool(stored and stored["reply"])
            items.append({**candidate, "call_reserved": reserved, "reply_archived": replied,
                "provider_outcome_unknown": reserved and not replied,
                "script_revision_id": result["script_revision_id"] if result else None,
                "artifact_hash": result["artifact_hash"] if result else None})
        self.authorization.require_current(access)
        return {"request": query.model_dump(mode="json"), "items": items[:query.limit],
            "next_after_id": items[query.limit - 1]["invocation_id"] if len(items) > query.limit else None,
            "generation_authorized": False, "execution_authorized": False}

    @staticmethod
    def _selection(request):
        return ScriptExecutionSelection(**{key: getattr(request, key) for key in ScriptExecutionSelection.model_fields})

    def _reply(self, request, stored, access):
        reservation = stored["reservation"]
        if reservation["request"] != request.model_dump(mode="json") or reservation["actor_id"] != access.actor_id:
            raise TestDesignResultIntegrityError("automation reservation was rebound")
        if not stored.get("reply"):
            raise GenerationOutcomeUnknown("automation call outcome is unknown; never resend it")
        receipt = stored["reply"]
        payload = self.replies.read(request.project_id, receipt["artifact_ref"], receipt["artifact_hash"])
        usage = payload.get("usage", {})
        expected = verify_generation_usage(GenerationModelPolicy.model_validate(reservation["policy"]), request.budget,
            usage.get("input_tokens"), usage.get("output_tokens"))
        if (acceptance_digest(payload) != receipt["artifact_hash"] or payload.get("schema") != SCRIPT_REPLY_SCHEMA
                or payload.get("request") != request.model_dump(mode="json") or payload.get("project_id") != request.project_id
                or any(payload.get(key) != reservation[key] for key in ("invocation_id", "actor_id", "call_id"))
                or response_digest(payload["content"]) != receipt["response_hash"]
                or usage != expected or receipt.get("usage") != expected):
            raise TestDesignResultIntegrityError("automation native response provenance mismatch")
        for ident in request.execution.source_binding_ids:
            access.require_binding(ident)
        self.authorization.require_current(access)
        return payload

    async def execute(self, request: ScriptExecutionRequest, *, invocation_id):
        request = ScriptExecutionRequest.model_validate(request.model_dump(mode="json"))
        access = self._access(request.project_id)
        stored = await asyncio.to_thread(self.repository.get, request.project_id, invocation_id)
        if stored is not None and stored.get("result"):
            view = await asyncio.to_thread(self.read, request.project_id, stored["result"]["script_revision_id"])
            if view["result"]["request"] != request.model_dump(mode="json") or view["result"]["actor_id"] != access.actor_id:
                raise TestDesignResultIntegrityError("automation result was rebound")
            return view["metadata"]
        access, prepared, model, policy, reservation, expected = await asyncio.to_thread(self._prepare, self._selection(request))
        if expected != request:
            raise GenerationBudgetInvalid("automation consent changed; preview and confirm again")

        def current():
            self.authorization.require_current(access)
            if self._prepare(self._selection(request))[-1] != request:
                raise GenerationBudgetInvalid("automation dependencies changed")

        if stored is not None:
            reply_payload = await asyncio.to_thread(self._reply, request, stored, access)
        else:
            call_id = str(uuid4())
            reserved = {"schema": SCRIPT_RESERVATION_SCHEMA, "project_id": request.project_id, "invocation_id": invocation_id,
                "actor_id": access.actor_id, "call_id": call_id, "generation_id": prepared["generation_pin"]["generation_id"],
                "request": request.model_dump(mode="json"),
                "policy": policy.model_dump(mode="json"), "model_binding": asdict(model.binding), "reservation": reservation,
                "reserved_at": datetime.now(timezone.utc).isoformat()}
            await asyncio.to_thread(self.repository.reserve, request, reserved, require_current=current)
            await asyncio.to_thread(current)
            system, content = script_messages(prepared, http_protocol=request.selected_http_protocol())
            started, reply = time.monotonic(), None
            try:
                reply = await asyncio.wait_for(self.provider.generate(system, content, model,
                    max_output_tokens=request.budget.max_output_tokens_per_call), timeout=GENERATION_TIMEOUT_SECONDS)
                if reply.usage_source != "provider":
                    raise GenerationBudgetInvalid("automation lacks native provider usage")
                usage = verify_generation_usage(policy, request.budget, reply.input_tokens, reply.output_tokens)
                await asyncio.to_thread(current)
                reply_payload = {"schema": SCRIPT_REPLY_SCHEMA, "project_id": request.project_id, "invocation_id": invocation_id,
                    "actor_id": access.actor_id, "request": request.model_dump(mode="json"), "call_id": call_id,
                    "content": reply.content, "usage": usage}
                ref, digest = await asyncio.to_thread(self.replies.put, request.project_id, reply_payload)
                call = self._call(request, model, call_id, invocation_id, started, reply, "success")
                await asyncio.to_thread(self.repository.record_reply, request, reply_payload, ref, digest, call, require_current=current)
            except BaseException:
                call = self._call(request, model, call_id, invocation_id, started, reply, "error")
                await asyncio.to_thread(self.repository.record_failure, request, invocation_id, call)
                raise
        proposal = validate_script_output(prepared, reply_payload["content"], http_protocol=request.selected_http_protocol())
        payload = {"schema": SCRIPT_RESULT_SCHEMA, "project_id": request.project_id,
            "script_revision_id": str(uuid5(NAMESPACE_URL, "nasus:automation-script:" + invocation_id)),
            "invocation_id": invocation_id, "actor_id": access.actor_id, "request": request.model_dump(mode="json"),
            "model_binding": asdict(model.binding), "call_id": reply_payload["call_id"],
            "response_hash": response_digest(reply_payload["content"]), "prepared": prepared,
            "raw_output": reply_payload["content"], "proposal": proposal, "status": "draft"}
        ref, digest = await asyncio.to_thread(self.results.put, request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise TestDesignResultIntegrityError("automation result archive mismatch")
        result = await asyncio.to_thread(self.repository.record_result, request, payload, ref, digest, require_current=current)
        self.authorization.require_current(access)
        return result

    def read(self, project_id, revision_id):
        access = self.authorization.scope(project_id)
        stored = self.repository.result(project_id, revision_id)
        metadata = stored["metadata"]
        payload = self.results.read(project_id, stored["artifact_ref"], metadata["artifact_hash"])
        request = ScriptExecutionRequest.model_validate(payload["request"])
        parent_reader = (request.case_approval_revision_id is not None
            and callable(getattr(self.admissions, "read_with_inputs", None)))
        if parent_reader:
            prepared = self._admission_input(request)
        else:
            prepared = self.inputs.replay(request.selection())
            if request.case_approval_revision_id is not None:
                self._admission(request, prepared, historical=True)
        if (request.project_id != project_id or acceptance_digest(payload) != metadata["artifact_hash"]
                or payload.get("schema") != SCRIPT_RESULT_SCHEMA or payload.get("status") != "draft"
                or any(payload.get(key) != metadata[key] for key in ("project_id", "script_revision_id", "invocation_id", "call_id", "response_hash"))
                or prepared != payload["prepared"] or request.input_digest != prepared["input_digest"]
                or validate_script_output(prepared, payload["raw_output"], http_protocol=request.selected_http_protocol()) != payload["proposal"]):
            raise TestDesignResultIntegrityError("automation draft history provenance mismatch")
        native = self.repository.get(project_id, metadata["invocation_id"])
        if native is None or native["reservation"]["model_binding"] != payload["model_binding"]:
            raise TestDesignResultIntegrityError("automation native call history mismatch")
        # Reading a draft is allowed for project readers, but the confirming
        # actor and exact response remain pinned independently of today's model.
        # _reply requires the actual reader's live scope, so verify the fixed
        # native archive here rather than impersonating its historical author.
        reply = native["reply"]
        archived = self.replies.read(project_id, reply["artifact_ref"], reply["artifact_hash"])
        if (archived["content"] != payload["raw_output"] or archived["request"] != payload["request"]
                or archived["actor_id"] != payload["actor_id"] or archived["call_id"] != payload["call_id"]
                or archived.get("schema") != SCRIPT_REPLY_SCHEMA or archived.get("project_id") != project_id
                or archived.get("invocation_id") != payload["invocation_id"]
                or archived.get("usage") != reply["usage"] or response_digest(archived["content"]) != payload["response_hash"]
                or payload["model_binding"]["config_id"] != request.model_config_id
                or payload["model_binding"]["config_digest"] != request.model_config_digest
                or metadata["input_digest"] != request.input_digest
                or metadata["mapping_revision_id"] != request.mapping_revision_id
                or metadata["mapping_artifact_hash"] != request.mapping_artifact_hash
                or metadata["script_count"] != payload["proposal"]["script_count"]
                or metadata["gap_count"] != payload["proposal"]["gap_count"]
                or metadata.get("execution_authorized") is not False):
            raise TestDesignResultIntegrityError("automation result differs from its archived reply")
        for ident in request.execution.source_binding_ids:
            access.require_binding(ident)
        # Legacy drafts remain inspectable; absence of admission is not current authority.
        current = request.case_approval_revision_id is not None
        try:
            if current:
                live_input = self._admission_input(request, current=True) if parent_reader else self.inputs.prepare(request.selection())
                current = live_input["input_digest"] == request.input_digest
                if current and not parent_reader:
                    self._admission(request, live_input)
        except (AutomationInputChanged, TestDesignMappingChanged, TestDesignScopeChanged, CaseApprovalChanged):
            current = False
        self.authorization.require_current(access)
        return {"metadata": metadata, "result": payload, "historical_not_live": True,
            "current_use": {"input_current": current, "execution_authorized": False}}

    @staticmethod
    def _call(request, model, call_id, invocation_id, started, reply, outcome):
        usage = (reply is not None and reply.usage_source == "provider" and type(reply.input_tokens) is int
            and type(reply.output_tokens) is int and reply.input_tokens >= 0 and reply.output_tokens >= 0)
        return LLMCall(id=call_id, occurred_at=datetime.now(timezone.utc), route="chat", purpose=SCRIPT_TOOL,
            provider=model.binding.provider, model_name=model.binding.model_name, selected_provider=model.binding.provider,
            selected_model_name=model.binding.model_name, runtime_mode="live", outcome=outcome,
            reason="native_script_reply_archived" if outcome == "success" else "reserved_script_call_failed_or_unknown_no_resend",
            project_id=request.project_id, tool_invocation_id=invocation_id, prompt_id="nasus.automation-script",
            prompt_version="v3" if request.http_protocol == "nasus.runner-http-execution.v3" else "v2" if request.http_protocol else "v1",
            model_calls=1, request_hash=acceptance_digest(request.model_dump(mode="json")),
            response_hash=response_digest(reply.content) if reply else "", input_token_count=reply.input_tokens if usage else 0,
            output_token_count=reply.output_tokens if usage else 0, usage_source="provider" if usage else "none",
            latency_ms=int((time.monotonic() - started) * 1000))

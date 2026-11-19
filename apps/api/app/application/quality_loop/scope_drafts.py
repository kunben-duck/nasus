"""Native, budgeted scope suggestions over a fixed confirmed context."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import time
from uuid import uuid4

from .generation_budget import GenerationBudgetInvalid, GenerationModelPolicy, reserve_generation_budget, verify_generation_usage
from .generation_executor import GenerationOutcomeUnknown
from .generation_execution_inputs import GENERATION_TIMEOUT_SECONDS
from .scope_draft_inputs import (SCOPE_DRAFT_PROMPT, SCOPE_DRAFT_SCHEMA, SCOPE_DRAFT_TOOL,
    ScopeDraftSelection, ScopeDraftRequest, scope_draft_messages, validate_scope_draft)
from .test_design_results import response_digest
from ...domain.platform.llm_call import LLMCall
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_scope import TestDesignScopeChanged, TestDesignScopeIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class ScopeDraftApplicationService:
    def __init__(self, scopes, profiles, policies, sources, provider, repository, artifacts):
        self.scopes, self.profiles, self.policies = scopes, profiles, policies
        self.authorization = scopes.authorization
        self.sources, self.provider, self.repository, self.artifacts = sources, provider, repository, artifacts

    def _context(self, project_id, context_id, digest=None, *, current=False):
        value = self.scopes.contexts.read(project_id, context_id)
        if digest is not None and value["metadata"]["artifact_hash"] != digest:
            raise TestDesignScopeIntegrityError("scope draft context hash mismatch")
        context = value["context"]
        if current and (value["current_use"]["stale"] or not (context.get("publication_pin") or context.get("iteration_pin"))
                or not context["required_constraints"] or any(item.get("oracle") is None
                    or item["authority"].get("status") != "approved" for item in context["required_constraints"])):
            raise TestDesignScopeChanged("scope drafting requires a current, independently confirmed context")
        pin = {key: value["metadata"][key] for key in
            ("context_id", "artifact_hash", "input_digest", "image_revision_id", "image_artifact_hash")}
        prepared = {"project_id": project_id, "context_pin": pin, "context": context, "prompt_version": SCOPE_DRAFT_PROMPT}
        return {**prepared, "input_digest": acceptance_digest(prepared)}, value

    def _prepare(self, selection):
        selection = ScopeDraftSelection.model_validate(selection.model_dump(mode="json"))
        access = self.authorization.scope(selection.project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("scope model egress requires a project administrator")
        prepared, _ = self._context(selection.project_id, selection.context_id, selection.context_artifact_hash, current=True)
        bindings = self.sources.bindings(prepared)
        for binding in bindings:
            access.require_binding(binding)
        model = self.profiles.resolve(selection.model_config_id, route="chat")
        counter = self.policies.resolve(model.binding)
        messages = scope_draft_messages(prepared)
        reservation = reserve_generation_budget(counter.policy, selection.budget, [counter.count(*messages)])
        plan = {"input_digest": prepared["input_digest"], "model_binding": asdict(model.binding),
            "policy": counter.policy.model_dump(mode="json"), "source_binding_ids": list(bindings),
            "source_scope_digest": access.fingerprint, "budget": selection.budget.model_dump(mode="json"),
            "reservation": reservation, "messages_hash": acceptance_digest(messages), "timeout_seconds": GENERATION_TIMEOUT_SECONDS}
        request = ScopeDraftRequest(**selection.model_dump(mode="json"), input_digest=prepared["input_digest"],
            model_config_digest=model.binding.config_digest, plan_digest=acceptance_digest(plan))
        self.authorization.require_current(access)
        return access, prepared, model, counter.policy, plan, request

    def preview(self, selection):
        _, _, model, _, plan, request = self._prepare(selection)
        return {"request": request.model_dump(mode="json"), "plan": plan,
            "provider": model.binding.provider, "model_name": model.binding.model_name,
            "destination": model.binding.base_url, "review_required": True, "generation_authorized": False}

    def require_receipt_access(self, project_id, context_id, context_artifact_hash):
        access = self.authorization.scope(project_id)
        prepared, _ = self._context(project_id, context_id, context_artifact_hash)
        for binding in self.sources.bindings(prepared):
            access.require_binding(binding)
        self.authorization.require_current(access)

    def history(self, project_id, context_id):
        access = self.authorization.scope(project_id)
        self._context(project_id, context_id)
        result = []
        for event in self.repository.history(project_id, context_id):
            states = self.repository.events(project_id, event["invocation_id"])
            for binding in event["payload"]["plan"]["source_binding_ids"]:
                access.require_binding(binding)
            result.append({"invocation_id": event["invocation_id"], "actor_id": event["actor_id"],
                "recorded_at": event["recorded_at"], "status": "draft" if "draft" in states else
                    "failed" if "failed" in states else "reply_archived" if "replied" in states else "reserved",
                "provider_outcome_unknown": "replied" not in states,
                "review_required": True, "generation_authorized": False})
        self.authorization.require_current(access)
        return {"items": result}

    def read(self, project_id, invocation_id):
        access = self.authorization.scope(project_id)
        states = self.repository.events(project_id, invocation_id)
        if "draft" not in states or "reserved" not in states or "replied" not in states:
            raise KeyError("scope model draft is not available")
        reservation = states["reserved"]["payload"]
        request = ScopeDraftRequest.model_validate(reservation["request"])
        prepared, context = self._context(project_id, request.context_id, request.context_artifact_hash)
        for binding in reservation["plan"]["source_binding_ids"]:
            access.require_binding(binding)
        ref = states["replied"]["payload"]
        payload = self.artifacts.read(project_id, ref["artifact_ref"], ref["artifact_hash"])
        usage = payload.get("usage", {})
        expected_usage = verify_generation_usage(GenerationModelPolicy.model_validate(reservation["plan"]["policy"]),
            request.budget, usage.get("input_tokens"), usage.get("output_tokens"))
        if (request.project_id != project_id or payload.get("request") != reservation["request"]
                or payload.get("call_id") != reservation["call_id"] or payload.get("invocation_id") != invocation_id
                or payload.get("actor_id") != states["reserved"]["actor_id"] or usage != expected_usage
                or prepared["input_digest"] != request.input_digest or usage != ref["usage"]
                or response_digest(payload["content"]) != ref["response_hash"]
                or acceptance_digest(reservation["plan"]) != request.plan_digest):
            raise TestDesignScopeIntegrityError("scope native reply provenance mismatch")
        draft = validate_scope_draft(prepared, payload["content"])
        if states["draft"]["payload"] != {"artifact_hash": ref["artifact_hash"], "draft_digest": acceptance_digest(draft)}:
            raise TestDesignScopeIntegrityError("scope draft derivation mismatch")
        self.authorization.require_current(access)
        return {"invocation_id": invocation_id, "context_id": request.context_id,
            "context_artifact_hash": request.context_artifact_hash, "actor_id": payload["actor_id"],
            "model_binding": reservation["model_binding"], "usage": usage, "artifact_hash": ref["artifact_hash"],
            **draft, "current_use": {"context_current": not context["current_use"]["stale"], "generation_authorized": False}}

    async def execute(self, request, *, invocation_id):
        request = ScopeDraftRequest.model_validate(request.model_dump(mode="json"))
        selection = ScopeDraftSelection(**{key: getattr(request, key) for key in ScopeDraftSelection.model_fields})
        access, prepared, model, policy, plan, expected = await asyncio.to_thread(self._prepare, selection)
        if request != expected:
            raise GenerationBudgetInvalid("scope draft inputs or consent changed; preview again")

        def current():
            self.authorization.require_current(access)
            if self._prepare(selection)[-1] != request:
                raise GenerationBudgetInvalid("scope draft inputs changed during generation")

        states = await asyncio.to_thread(self.repository.events, request.project_id, invocation_id)
        if states:
            if states.get("reserved", {}).get("payload", {}).get("request") != request.model_dump(mode="json"):
                raise TestDesignScopeIntegrityError("scope draft invocation was rebound")
            if states["reserved"]["actor_id"] != access.actor_id:
                raise SourceAccessDenied("scope draft recovery requires its original actor")
            if "draft" in states:
                return await asyncio.to_thread(self.read, request.project_id, invocation_id)
            if "replied" not in states:
                raise GenerationOutcomeUnknown("scope model result is unknown; no automatic resend")
            reply_record = states["replied"]["payload"]
            payload = await asyncio.to_thread(self.artifacts.read, request.project_id,
                reply_record["artifact_ref"], reply_record["artifact_hash"])
        else:
            call_id = str(uuid4())
            await asyncio.to_thread(self.repository.record, request, invocation_id, access.actor_id, "reserved",
                {"request": request.model_dump(mode="json"), "call_id": call_id, "plan": plan,
                    "model_binding": asdict(model.binding)}, require_current=current)
            started, reply = time.monotonic(), None
            try:
                await asyncio.to_thread(current)
                reply = await asyncio.wait_for(self.provider.generate(*scope_draft_messages(prepared), model,
                    max_output_tokens=request.budget.max_output_tokens_per_call), timeout=GENERATION_TIMEOUT_SECONDS)
                if reply.usage_source != "provider":
                    raise GenerationBudgetInvalid("scope draft lacks provider usage")
                usage = verify_generation_usage(policy, request.budget, reply.input_tokens, reply.output_tokens)
                payload = {"schema": SCOPE_DRAFT_SCHEMA, "project_id": request.project_id,
                    "invocation_id": invocation_id, "request": request.model_dump(mode="json"),
                    "actor_id": access.actor_id, "call_id": call_id, "content": reply.content, "usage": usage}
                ref, digest = await asyncio.to_thread(self.artifacts.put, request.project_id, payload)
                reply_record = {"artifact_ref": ref, "artifact_hash": digest, "usage": usage,
                    "response_hash": response_digest(reply.content)}
                await asyncio.to_thread(self.repository.record, request, invocation_id, access.actor_id, "replied",
                    reply_record, call=self._call(request, model, invocation_id, call_id, started, reply, "success"),
                    require_current=current)
            except BaseException:
                # Reservation remains even if authority was revoked while the call ran.
                try:
                    await asyncio.to_thread(self.repository.record, request, invocation_id, access.actor_id, "failed",
                        {"reason": "reserved_call_failed_or_unknown_no_resend"},
                        call=self._call(request, model, invocation_id, call_id, started, reply, "error"), require_current=current)
                except (ValueError, PermissionError):
                    pass
                raise
        draft = validate_scope_draft(prepared, payload["content"])
        await asyncio.to_thread(self.repository.record, request, invocation_id, access.actor_id, "draft",
            {"artifact_hash": reply_record["artifact_hash"], "draft_digest": acceptance_digest(draft)}, require_current=current)
        return await asyncio.to_thread(self.read, request.project_id, invocation_id)

    @staticmethod
    def _call(request, model, invocation_id, call_id, started, reply, outcome):
        usage = (reply is not None and reply.usage_source == "provider"
            and all(type(value) is int and value >= 0 for value in (reply.input_tokens, reply.output_tokens)))
        return LLMCall(id=call_id, occurred_at=datetime.now(timezone.utc), route="chat", purpose=SCOPE_DRAFT_TOOL,
            provider=model.binding.provider, model_name=model.binding.model_name, selected_provider=model.binding.provider,
            selected_model_name=model.binding.model_name, runtime_mode="live", outcome=outcome,
            reason="native_scope_reply" if outcome == "success" else "scope_reply_failed_or_unknown",
            prompt_id=SCOPE_DRAFT_PROMPT, prompt_version="v1", project_id=request.project_id,
            tool_invocation_id=invocation_id, model_calls=1, latency_ms=int((time.monotonic() - started) * 1000),
            input_token_count=reply.input_tokens if usage else 0, output_token_count=reply.output_tokens if usage else 0,
            usage_source="provider" if usage else "none", request_hash=acceptance_digest(request.model_dump(mode="json")),
            response_hash=response_digest(reply.content) if reply else "")

"""Cumulative semantic memory. Business facts and authorization remain external."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from .agent_models import ConversationSummaryCheckpoint
from .memory_ports import ConversationMemoryJobPort, ConversationSummaryModelPort
from .memory_models import ConversationDigest
from ..platform.actor_context import current_actor
from ...domain.agent.conversation_memory import (
    ContextBudgetExceeded, ConversationHistory, completed_messages,
    compactable_prefix, message_text, validate_digest,
)

logger = logging.getLogger(__name__)


class SemanticConversationMemory:
    def __init__(self, *, jobs: ConversationMemoryJobPort, model: ConversationSummaryModelPort,
                 conversation, checkpoints, guard, publish):
        self.jobs, self.model = jobs, model
        self.conversation, self.checkpoints, self.guard, self.publish = conversation, checkpoints, guard, publish

    def latest(self, conversation_id):
        checkpoints = [c for c in self.checkpoints() if c.conversation_id == conversation_id]
        return max(checkpoints, key=lambda c: c.created_at) if checkpoints else None

    def valid_checkpoint(self, conversation):
        scope = self.guard(conversation)
        checkpoint = self.latest(conversation.id)
        if checkpoint and checkpoint.memory_payload.get("format_version") == 2 and checkpoint.memory_payload.get("scope") == scope:
            return checkpoint
        return None

    def history(self, conversation):
        checkpoint = self.valid_checkpoint(conversation)
        messages = completed_messages(conversation)
        if checkpoint:
            ids = [m.id for m in messages]
            if checkpoint.message_range_end not in ids:
                raise ValueError("summary coverage is no longer present")
            messages = messages[ids.index(checkpoint.message_range_end) + 1:]
        prefix = checkpoint.summary_text if checkpoint else "No semantic checkpoint; original messages retained."
        return ConversationHistory(prefix, [{"role": m.role, "content": message_text(m)} for m in messages],
                                   self.model.budget(), self.model.counter().count)

    def _payload(self, conversation, prefix, checkpoint):
        allowed_refs = {ref.removeprefix("tool_invocation:").removeprefix("tool:") for m in prefix for ref in m.tool_refs}
        observations = [{"ref": "tool:" + inv.id, "tool_id": inv.tool_id, "status": inv.status,
                         "summary": str(getattr(inv.result, "summary", ""))[:1000]}
                        for inv in conversation.tool_invocations if inv.id in allowed_refs]
        return {"conversation_id": conversation.id,
                "previous_digest": checkpoint.memory_payload["digest"] if checkpoint else None,
                "messages": [{"ref": "message:" + m.id, "role": m.role, "status": m.status, "text": message_text(m)} for m in prefix],
                "observations": observations}

    async def maybe_schedule(self, conversation):
        # Only persist dispatch intent here. Never call a model or Temporal on message POST.
        try:
            history = self.history(conversation)
            if self.model.counter().count(str(history)) >= self.model.budget().soft_limit:
                self.schedule(conversation)
        except (PermissionError, ContextBudgetExceeded):
            return None
        return None

    def schedule(self, conversation, *, force=False):
        scope = self.guard(conversation)
        previous = self.valid_checkpoint(conversation)
        parent = self.latest(conversation.id)
        messages = completed_messages(conversation)
        prefix = messages if force else compactable_prefix(messages)
        if previous:
            ids = [m.id for m in prefix]
            if previous.message_range_end in ids:
                prefix = prefix[ids.index(previous.message_range_end) + 1:]
            else:
                prefix = []
        if not prefix:
            return None
        counter, budget = self.model.counter(), self.model.budget()
        # Rebuild legacy history in bounded complete-turn batches, never from old truncated text.
        while prefix and counter.count(json.dumps(self._payload(conversation, prefix, previous), ensure_ascii=False)) > budget.input_limit // 2:
            starts = [i for i, m in enumerate(prefix) if m.role == "user" and i > 0]
            if not starts:
                raise ContextBudgetExceeded("A historical turn is too large to summarize safely; narrow its attached content.")
            prefix = prefix[:starts[-1]]
        binding = self.model.binding()
        identity = [conversation.id, parent.id if parent else None, prefix[-1].id, scope, binding]
        actor = current_actor()
        job = {"id": "memory_" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:32],
               "conversation_id": conversation.id, "parent_id": parent.id if parent else None,
               "previous_id": previous.id if previous else None,
               "end_id": prefix[-1].id, "start_id": prefix[0].id, "scope": scope,
               "model_binding": binding, "actor": actor.user.model_dump(mode="json") if actor else None}
        self.guard(conversation)
        return self.jobs.enqueue(job)

    async def run(self, job_id):
        job = self.jobs.claim(job_id)
        if job is None:
            return self.jobs.get(job_id)
        started = time.monotonic()
        try:
            conversation = self.conversation(job["conversation_id"])
            if self.guard(conversation) != job["scope"]:
                raise ValueError("memory_scope_changed")
            previous = self.valid_checkpoint(conversation)
            if (previous.id if previous else None) != job["previous_id"]:
                raise ValueError("checkpoint_changed")
            messages = completed_messages(conversation)
            ids = [m.id for m in messages]
            prefix = messages[ids.index(job["start_id"]):ids.index(job["end_id"]) + 1]
            payload = self._payload(conversation, prefix, previous)
            if job.get("reason"):
                payload["previous_attempt_error"] = job["reason"]
            origins = {"message:" + m.id: m.role for m in prefix}
            origins.update({o["ref"]: "tool" for o in payload["observations"]})
            if previous:
                origins.update(previous.memory_payload["origins"])
            digest, usage = await self.model.summarize(payload, job["model_binding"])
            validate_digest(digest, origins)
            if previous:
                old = ConversationDigest.model_validate(previous.memory_payload["digest"])
                # Critical constraints must survive verbatim, even when marked superseded.
                if any(not any(e.text == prior.text and set(prior.refs).issubset(e.refs) for e in digest.constraints)
                       for prior in old.constraints):
                    raise ValueError("summary_dropped_constraints")
            if self.guard(self.conversation(conversation.id)) != job["scope"]:
                raise ValueError("memory_scope_changed")
            if self.model.binding() != job["model_binding"]:
                raise ValueError("summary_model_changed")
            rendered = digest.render()
            token_count = self.model.counter().count(rendered)
            if token_count > self.model.budget().input_limit // 3:
                raise ValueError("summary_output_exceeds_budget")
            checkpoint = ConversationSummaryCheckpoint(id="chk_" + job["id"], conversation_id=conversation.id,
                message_range_start=previous.message_range_start if previous else prefix[0].id,
                message_range_end=prefix[-1].id, summary_text=rendered,
                summary_token_count=token_count, created_by="system", created_at=datetime.now(timezone.utc).isoformat(),
                memory_payload={"format_version": 2, "parent_id": job["parent_id"], "scope": job["scope"],
                    "digest": digest.model_dump(mode="json"), "origins": origins, "model_binding": job["model_binding"],
                    "usage": usage, "duration_ms": round((time.monotonic() - started) * 1000),
                    "input_count": self.model.counter().count(json.dumps(payload, ensure_ascii=False)),
                    "counting_method": self.model.counter().kind})
            if self.jobs.commit(job, checkpoint):
                await self.publish(conversation.id, checkpoint.id)
        except Exception as exc:
            # Never persist provider response bodies, prompts or credentials in error metadata.
            logger.warning("Conversation memory job %s failed (%s)", job_id, type(exc).__name__)
            validation_reasons = {"summary contains an unknown reference": "summary_invalid_reference",
                                  "summary origin does not match its evidence": "summary_invalid_origin",
                                  "empty summary": "summary_empty"}
            reason = str(exc) if isinstance(exc, ValueError) and str(exc) in {
                "summary_model_changed", "memory_scope_changed", "checkpoint_changed",
                "summary_dropped_constraints", "summary_output_exceeds_budget"} else "summary_model_unavailable"
            reason = validation_reasons.get(str(exc), reason)
            if isinstance(exc, PermissionError):
                reason = "memory_scope_changed"
            self.jobs.fail(job_id, reason, job["attempts"])
        return self.jobs.get(job_id)

    async def compact(self, conversation, *, force=False):
        job = self.schedule(conversation, force=force)
        if job is None:
            return self.valid_checkpoint(conversation)
        deadline = time.monotonic() + 135
        while time.monotonic() < deadline:
            result = await self.run(job["id"])
            if result["status"] == "completed":
                return self.valid_checkpoint(self.conversation(conversation.id))
            if result["status"] in {"failed", "superseded"}:
                raise ContextBudgetExceeded("Conversation memory could not be refreshed; original history is retained. Please retry.")
            await asyncio.sleep(0.2)
        raise ContextBudgetExceeded("Conversation memory is still being prepared. Please retry.")

    async def prepare(self, conversation, system, context, user_message=None, *, inspect_only=False):
        degraded_reason = None
        for _ in range(16):
            history = self.history(conversation)
            if user_message is None:
                count = self.model.counter().count(system + context + str(history)) + 512
            else:
                count = self.model.counter().count(json.dumps([
                    {"role": "system", "content": system}, *history.provider_messages(user_message, context)], ensure_ascii=False)) + 128
            budget = self.model.budget()
            if inspect_only:
                break
            if count < budget.soft_limit:
                break
            if count < budget.hard_limit:
                try:
                    self.schedule(conversation)
                except ContextBudgetExceeded:
                    degraded_reason = "summary_input_exceeds_budget"
                break
            before = self.valid_checkpoint(conversation)
            try:
                after = await self.compact(conversation)
            except ContextBudgetExceeded:
                if count <= budget.input_limit:
                    degraded_reason = "summary_unavailable_originals_fit"
                    break
                raise
            if after is None or (before and before.id == after.id):
                if count <= budget.input_limit:
                    break
                raise ContextBudgetExceeded("Conversation context exceeds its budget; no safe history can be removed.")
            conversation = self.conversation(conversation.id)
        else:
            raise ContextBudgetExceeded("Historical memory is being rebuilt; please retry.")
        async def refresh(actual_system, actual_user, actual_context):
            current = self.conversation(conversation.id)
            refreshed, _ = await self.prepare(current, actual_system, actual_context, actual_user)
            return refreshed
        history.refresh = refresh
        summary = self.status(conversation)
        if degraded_reason:
            summary["degraded_reason"] = degraded_reason
        return history, {"input_limit": budget.input_limit, "estimated_input_tokens": count,
                         "counting_method": self.model.counter().kind, "summary": summary}

    def status(self, conversation):
        checkpoint = self.valid_checkpoint(conversation)
        job = self.jobs.latest(conversation.id)
        data = checkpoint.memory_payload if checkpoint else {}
        return {"format_version": 2 if checkpoint else 1, "checkpoint_id": checkpoint.id if checkpoint else None,
                "coverage_end": checkpoint.message_range_end if checkpoint else None,
                "job_status": job["status"] if job else "idle", "degraded_reason": job["reason"] if job else None,
                "metrics": {"duration_ms": data.get("duration_ms"), "input_count": data.get("input_count"),
                    "summary_token_count": checkpoint.summary_token_count if checkpoint else None,
                    "usage": data.get("usage", {})}}

    def recall(self, conversation_id, *, query="", message_id=None, offset=0, limit=10):
        conversation = self.conversation(conversation_id)
        self.guard(conversation)
        messages = completed_messages(conversation)
        if message_id:
            messages = [m for m in messages if m.id == message_id]
        elif query:
            terms = query.casefold().split()
            messages = [m for m in messages if all(t in message_text(m).casefold() for t in terms)]
        else:
            raise ValueError("query or message_id is required")
        offset, limit = max(0, int(offset)), max(1, min(10, int(limit)))
        rows = messages[-limit:] if not message_id else messages
        result = [{"message_id": m.id, "role": m.role, "text": message_text(m)[offset:offset + 4000],
                   "offset": offset, "next_offset": offset + 4000 if len(message_text(m)) > offset + 4000 else None} for m in rows]
        self.guard(conversation)
        return {"messages": result, "matched_count": len(messages), "reference_only": True}

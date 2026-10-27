"""Synthetic execution receipts for persistence tests; never a real model claim."""
from datetime import datetime, timezone
import json
from uuid import uuid4

from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest, GENERATION_TOOL, response_digest
from apps.api.app.domain.platform.llm_call import LLMCall
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.llm_call_repository import SQLAlchemyLLMCallRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_link_model import saved_config
from apps.api.tests.test_test_design_generation import case_output


def seed_generation_execution(service, selection, actor_id, *, conversation_id=None, config=None):
    encrypted = None
    if config is None:
        config = saved_config(config_id=uuid4().hex)
        encrypted = service.profiles.secrets.encrypt_api_key("synthetic-result-fixture-key")
        service.profiles.repository.save_model_config(config, encrypted)
    binding = service.profiles.resolve(config.config_id).binding
    prepared = service.generation.prepare(selection)
    request = GenerationResultRequest(**selection.model_dump(), input_digest=prepared["input_digest"],
        model_config_id=config.config_id, model_config_digest=binding.config_digest)
    content = json.dumps(case_output(prepared))
    invocation_id, call_id = uuid4().hex, uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=GENERATION_TOOL, status="running",
            summary="Synthetic execution protocol fixture; no model or target was invoked", conversation_id=conversation_id,
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": actor_id,
                           "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    call = LLMCall(id=call_id, occurred_at=datetime.now(timezone.utc), route="chat", purpose=GENERATION_TOOL,
        provider=binding.provider, model_name=binding.model_name, selected_provider=binding.provider, selected_model_name=binding.model_name,
        runtime_mode="live", outcome="success", reason="Synthetic native-success receipt fixture, NOT an actual provider call",
        project_id=selection.project_id, conversation_id=conversation_id, tool_invocation_id=invocation_id,
        model_calls=1, input_token_count=123, output_token_count=456, usage_source="provider",
        request_hash=acceptance_digest(request.model_dump(mode="json")), response_hash=response_digest(content))
    SQLAlchemyLLMCallRepository().persist_llm_call(call)
    return {"request": request, "invocation_id": invocation_id, "call_id": call_id, "content": content,
            "config": config, "encrypted": encrypted, "prepared": prepared}

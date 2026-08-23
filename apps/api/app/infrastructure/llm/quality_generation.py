from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from pydantic import ValidationError

from ...application.platform.model_settings import StudioSettings
from ...application.platform.prompts import PromptRegistryPort
from ...application.quality_loop.generation import (
    QualityGenerationError,
    QualityGenerationRequest,
    QualityGenerationResult,
    fallback_generation_output,
    generation_summary,
    generation_title,
    output_model_for_stage,
    prompt_for_stage,
    validate_generation_output,
)
from ...application.quality_loop.quality_models import QualityAssetGenerationMetadata
from ...domain.platform.llm_call import LLMCallContext
from .gateway import LLMGateway


SettingsProvider = Callable[[], StudioSettings]
SecretProvider = Callable[[str], str]


class LLMQualityGenerationAdapter:
    """Versioned structured-output adapter for quality asset generation."""

    def __init__(
        self,
        *,
        llm: LLMGateway,
        settings_provider: SettingsProvider,
        custom_api_key_provider: SecretProvider,
        fail_closed: bool,
        prompt_registry: PromptRegistryPort | None = None,
    ) -> None:
        self._llm = llm
        self._settings_provider = settings_provider
        self._custom_api_key_provider = custom_api_key_provider
        self._fail_closed = fail_closed
        self._prompt_registry = prompt_registry

    async def generate(self, request: QualityGenerationRequest) -> QualityGenerationResult:
        prompt = prompt_for_stage(request.stage, self._prompt_registry)
        if self._fail_closed and (not request.task_context or not request.quality_profile):
            raise QualityGenerationError(
                f"{prompt.prompt_id} requires a materialized TaskContext and QualityProfile in production"
            )
        output_model = output_model_for_stage(request.stage)
        fallback_payload = fallback_generation_output(
            request.stage,
            request.us_id,
            tool_input=request.tool_input,
        )
        fallback_text = json.dumps(fallback_payload, ensure_ascii=False, sort_keys=True)
        settings = self._settings_provider()
        reply = await self._llm.generate_reply(
            settings=settings,
            system_prompt=(
                f"{prompt.system_prompt}\n"
                f"Output schema reference: {prompt.output_schema_ref}\n"
                f"JSON Schema: {json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)}"
            ),
            user_message=(
                f"Generate the {request.stage} quality asset for project {request.project_id}, "
                f"US {request.us_id}."
            ),
            context_snapshot=json.dumps(request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
            history_snapshot="No conversation history is authoritative for this generation request.",
            fallback_text=fallback_text,
            custom_api_key=self._custom_api_key_provider("chat"),
            call_context=LLMCallContext(
                purpose=f"quality.{request.stage}.generate",
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.prompt_version,
                project_id=request.project_id,
                task_id=request.us_id,
                conversation_id=request.conversation_id,
                agent_goal_id=request.agent_goal_id,
                tool_invocation_id=request.tool_invocation_id,
            ),
        )

        if reply.mode != "live":
            if self._fail_closed:
                raise QualityGenerationError(
                    f"{prompt.prompt_id} requires a live model provider in production: {reply.reason}"
                )
            payload = fallback_payload
            mode = "fallback"
            reason = reply.reason
        else:
            try:
                payload = validate_generation_output(request.stage, self._extract_json(reply.content))
                mode = "live"
                reason = reply.reason
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                if self._fail_closed:
                    raise QualityGenerationError(
                        f"{prompt.prompt_id} returned invalid structured output: {exc}"
                    ) from exc
                payload = fallback_payload
                mode = "fallback"
                reason = "invalid_structured_output"

        generated_at = datetime.now(timezone.utc).isoformat()
        return QualityGenerationResult(
            stage=request.stage,
            title=generation_title(request.stage),
            summary=generation_summary(request.stage, payload),
            structured_output=payload,
            generation=QualityAssetGenerationMetadata(
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.prompt_version,
                provider=reply.provider,
                model_name=reply.model_name,
                mode=mode,
                reason=reason,
                input_context_hash=request.input_context_hash(),
                generated_at=generated_at,
            ),
        )

    @staticmethod
    def _extract_json(content: str) -> dict:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("model response did not contain a JSON object")
        payload = json.loads(stripped[start : end + 1])
        if not isinstance(payload, dict):
            raise TypeError("model response must be a JSON object")
        return payload


__all__ = ["LLMQualityGenerationAdapter"]

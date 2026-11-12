"""Guide a Build conversation through real source intake and governed image work."""
from __future__ import annotations

import re

from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.agent.goal_creation import ACTIVE_AGENT_GOAL_STATUSES
from ..platform.errors import PlatformApplicationError
from ..platform.tool_models import ToolInvocationRequest
from .build_dialogue_inputs import (
    BuildIntake, STATE_KEY, is_intake_confirmation,
    read_intake, validate_fields,
)
from .build_dialogue_text import goal_summary, prompt_for
from .build_dialogue_recovery import BuildDialogueRecovery, creation_receipts, recoverable_project
from .build_dialogue_routing import build_turn_kind, is_project_name_question


class GuidedBuildConversation:
    def __init__(self, *, runtime, conversations, build_entries, extractor, snapshots, revisions, project_reader):
        self.runtime, self.conversations = runtime, conversations
        self.build_entries, self.extractor = build_entries, extractor
        self.recovery = BuildDialogueRecovery(conversations, snapshots, revisions)
        self.project_reader = project_reader

    async def handle(self, conversation_id, content):
        conversation = self.runtime.get_conversation(conversation_id)
        if conversation.space_type != "build":
            return None
        state = read_intake(conversation)
        if is_project_name_question(content):
            return await self._project_name(conversation, content)
        kind = build_turn_kind(content)
        starting = state is None
        if state is None:
            locale = "zh" if re.search(r"[\u4e00-\u9fff]", content) else "en"
            receipts = creation_receipts(conversation)
            recognized = kind or await self.extractor.recognizes(conversation, content)
            if not recognized:
                return None
            if conversation.project_id or receipts:
                recovered = self.recovery.recover(conversation, content, locale)
                if recovered is None:
                    choices = "\n".join(f"- `{'选择项目' if locale == 'zh' else 'select project'} {project_id}`" for project_id in receipts)
                    message = await self.runtime.append_message(conversation.id, "assistant",
                        ("这条对话涉及多个项目，暂时无法确定你要继续哪一个。请回复下面的一项，不需要重新创建项目：\n\n" if locale == "zh"
                         else "This conversation contains several projects. Select one below to continue without creating another project:\n\n") + choices,
                        metadata={"planner_kind": "build_project_selection"})
                    return {"message_id": message.id}
                conversation, state = recovered
            else:
                state = BuildIntake(locale=locale)
        if state.project_id and conversation.project_id != state.project_id:
            raise PlatformApplicationError("build_intake_scope_changed", "The build conversation scope changed.", 409)
        if kind == "history":
            rows = [f"- `{item.tool_id}`: {item.status} · {item.summary}" for item in conversation.tool_invocations]
            return await self._say(conversation.id, state,
                (("本次对话的执行记录：\n\n" if state.locale == "zh" else "Execution history for this conversation:\n\n") + "\n".join(rows))
                if rows else ("本次对话还没有执行过工具。" if state.locale == "zh" else "No tools have run in this conversation yet."))
        if state.stage == "existing":
            # None means pass through, never fall into intake and reset its stage.
            return await self._existing(conversation, state, content, kind)
        if state.stage == "building":
            if kind is None:
                return None
            return await self._building(conversation, state, content)
        return await self._intake(conversation, state, content, starting=starting)

    async def _project_name(self, conversation, content):
        zh = bool(re.search(r"[\u4e00-\u9fff]", content))
        project_id = recoverable_project(conversation, content)
        if project_id:
            project = self.project_reader(project_id)
            text = f"当前项目名称是 **{project.name}**。" if zh else f"The current project is **{project.name}**."
        elif creation_receipts(conversation):
            text = ("这条对话涉及多个项目，尚未确定当前项目。请先选择要继续的项目。" if zh
                    else "This conversation contains multiple projects. Select the project to continue first.")
        else:
            text = ("当前还没有创建项目。你可以先告诉我项目名称。" if zh else "No project has been created yet. Tell me the project name to begin.")
        message = await self.runtime.append_message(conversation.id, "assistant", text,
            metadata={"planner_kind": "project_identity", "project_id": project_id})
        return {"message_id": message.id}

    async def _intake(self, conversation, state, content, *, starting=False, fields=None):
        conversation_id = conversation.id
        if state.stage == "review" and is_intake_confirmation(content):
            return await self._capture_and_build(conversation, state)
        if fields is None:
            fields = validate_fields(await self.extractor.extract(conversation, content, state))
        if state.project_id:
            fields.pop("project_name", None)
        if not fields:
            if starting or build_turn_kind(content) is not None or is_intake_confirmation(content):
                return await self._say(conversation_id, state, prompt_for(state))
            return None
        if state.capture_started and any(key in fields and fields[key] != getattr(state, key)
                for key in ("code", "code_ref", "requirements", "tests")):
            return await self._say(conversation_id, state,
                "本次来源已经登记，不能把失败的旧来源当作已删除。请恢复原地址的可访问性后重新确认；如果需要换仓库或资料，请点击“开始新的构建对话”。尚未采集前可以自由修改资料。"
                if state.locale == "zh" else "These sources have already been registered. Replacing a URL does not remove its failed binding. Restore access to the original sources and confirm again, or start a new build conversation with different inputs. Inputs can be edited freely before capture.")
        if fields:
            state = state.model_copy(update={**fields, "revision": state.revision + 1})
        if state.requirements and state.tests:
            state.optional_decided = True
        if not state.project_name:
            state.stage = "name"
            return await self._say(conversation_id, state, prompt_for(state))
        if not state.project_id:
            # Persist the identity before any write so Activity replay retains
            # the same tool idempotency keys even after a process restart.
            await self._say(conversation_id, state,
                f"正在创建项目 **{state.project_name}**。" if state.locale == "zh" else f"Creating **{state.project_name}**.")
            invocation = await self._tool(conversation_id, state, "project.create", {"name": state.project_name}, fixed=True)
            if invocation.status != "completed":
                return await self._tool_blocked(conversation_id, state, invocation)
            conversation = self.conversations.bind_created_project(conversation_id, invocation)
            state.project_id = conversation.project_id
        state.stage = "review" if state.code and state.optional_decided else "sources"
        return await self._say(conversation_id, state, prompt_for(state))

    async def _capture_and_build(self, conversation, state):
        if not state.code or state.project_id != conversation.project_id:
            raise PlatformApplicationError("invalid_build_inputs", "A verified project and code source are required.", 409)
        if not state.capture_started:
            state.capture_started = True
            await self._say(conversation.id, state,
                "正在采集已确认的资料，代码只会被读取，不会运行。" if state.locale == "zh" else "Capturing the confirmed sources. Repository code will be read, not executed.")
        for tool_id, payload in (
            ("system_image.sources.register", {"project_id": state.project_id, "source_specs": state.source_specs()}),
            ("system_image.sources.ingest", {"project_id": state.project_id}),
        ):
            invocation = await self._tool(conversation.id, state, tool_id, payload)
            if invocation.status != "completed" or invocation.result is None or invocation.result.requires_followup:
                return await self._tool_blocked(conversation.id, state, invocation)
        return await self._prepare_build(conversation, state)

    async def _prepare_build(self, conversation, state):
        active = [item for item in conversation.agent_goals if item.status in ACTIVE_AGENT_GOAL_STATUSES]
        if active:
            if len(active) != 1 or active[0].goal_template != "system_image_build" or active[0].project_id != state.project_id:
                return await self._other_task(conversation, state)
            state.stage, state.goal_id = "building", active[0].id
            return await self._building(conversation, state, "status")
        # Compilation verifies the captured manifest and fixed target again;
        # intake consent never grants structural/model/publication budgets.
        decision = self.build_entries.plan(
            conversation.model_copy(update={"space_type": "project"}),
            "Build the system image for this project.",
        )
        if decision is None or decision.agent_goal is None:
            message = decision.clarification.question if decision and decision.clarification else "Build preparation could not be verified."
            return await self._say(conversation.id, state, message)
        state.stage = "building"
        await self._say(conversation.id, state, prompt_for(state))
        goal = await self.runtime.start_goal_from_proposal(conversation.id, decision.agent_goal)
        state.goal_id = goal.id
        result = await self._say(conversation.id, state, goal_summary(goal, state.locale))
        return {**result, "agent_goal": goal}

    def _image_status(self, state):
        return self.recovery.status(state)

    async def _other_task(self, conversation, state):
        state.stage, state.goal_id = "existing", None
        return await self._say(conversation.id, state,
            "当前对话还有其他未结束的任务，不能把它当成系统画像构建任务。你仍可查询画像状态；继续构建前，请先在 Agent 空间检查并完成或取消原任务。不会自动替换或取消它。"
            if state.locale == "zh" else "Another unfinished task controls this conversation; it is not this image build. You can still check image status. Review and finish or cancel the original task in Agent space before building. It will not be replaced or cancelled automatically.")

    async def _existing(self, conversation, state, content, kind):
        fields = {}
        if kind is None:
            fields = validate_fields(await self.extractor.extract(conversation, content, state))
            fields.pop("project_name", None)
            if not fields:
                return None
        status = self._image_status(state)
        # A question never starts, resumes, recaptures or publishes work.
        continuing = kind in {"continue", "build"}
        if status["next_action"] == "provide_sources" and (fields or continuing):
            state.stage = "sources"
            return await self._intake(conversation, state, content, fields=fields)
        if continuing and status["next_action"] == "build_candidate":
            return await self._prepare_build(conversation, state)
        if kind == "capture" and status["next_action"] == "capture_sources":
            invocation = await self._tool(conversation.id, state, "system_image.sources.ingest", {"project_id": state.project_id})
            if invocation.status != "completed" or invocation.result is None or invocation.result.requires_followup:
                return await self._tool_blocked(conversation.id, state, invocation)
            return await self._prepare_build(conversation, state)
        return await self._say(conversation.id, state, status["summary"], image_status=status)

    async def _building(self, conversation, state, content):
        kind = build_turn_kind(content)
        if kind is None:
            return None
        goal = (next((item for item in conversation.agent_goals if item.id == state.goal_id), None)
                if state.goal_id else self.runtime.active_goal_for_conversation(conversation.id))
        if state.goal_id and goal is None:
            return await self._say(conversation.id, state,
                "暂时无法读取本次构建目标，请刷新核对；不会替换成其他任务。" if state.locale == "zh" else "This build goal could not be read. Reload to verify it; no other goal will be substituted.")
        if goal is None:
            goals = [item for item in conversation.agent_goals
                     if item.goal_template == "system_image_build" and item.project_id == state.project_id]
            goal = goals[-1] if goals else None
        if goal is None:
            if kind == "status":
                status = self._image_status(state)
                return await self._say(conversation.id, state, status["summary"], image_status=status)
            # Recover a crash between the durable intake transition and goal
            # creation using the exact saved inputs and idempotent source tools.
            return await (self._capture_and_build(conversation, state) if state.code else self._prepare_build(conversation, state))
        if goal.goal_template != "system_image_build" or goal.project_id != state.project_id:
            return await self._other_task(conversation, state)
        if goal.status == "completed":
            status = self._image_status(state)
            return await self._say(conversation.id, state, status["summary"], image_status=status)
        if kind == "continue" and goal.status == "paused" and goal.pause_reason in {
            "waiting_confirmation", "structural_candidate_review", "reference_candidate_review",
        }:
            checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
            goal = await self.runtime.resume_goal(goal.id, expected_resume=checkpoint)
            result = await self._say(conversation.id, state, goal_summary(goal, state.locale))
            return {**result, "agent_goal": goal}
        result = await self._say(conversation.id, state, goal_summary(goal, state.locale))
        return {**result, "agent_goal": goal}

    async def _tool(self, conversation_id, state, tool_id, payload, *, fixed=False):
        invocation = await self.runtime.create_tool_invocation(ToolInvocationRequest(
            conversation_id=conversation_id, tool_id=tool_id, input=payload,
            initiator_surface="chat", initiator_actor="agent",
            idempotency_key=f"intake:{state.intake_id}:{0 if fixed else state.revision}:{tool_id}",
        ))
        return invocation

    async def _tool_blocked(self, conversation_id, state, invocation):
        prefix = "这一步尚未完成：" if state.locale == "zh" else "This step has not completed: "
        text = prefix + invocation.summary
        if invocation.status == "failed" or (invocation.result and invocation.result.requires_followup):
            # The failed attempt remains auditable; an explicit subsequent
            # confirmation gets fresh keys rather than replaying that failure.
            state = state.model_copy(update={"revision": state.revision + 1})
            text += ("\n\n请检查原路径是否存在、引用及访问权限，恢复后重新确认；已创建的项目会保留。更换来源请开始新的构建对话，避免把旧失败来源混入新画像。"
                     if state.locale == "zh" else "\n\nRestore the original path, ref or access and confirm again. The project is retained. Use a new build conversation for different sources; old failed bindings are not silently removed.")
        result = await self._say(conversation_id, state, text)
        return {**result, "tool_invocation": invocation}

    async def _say(self, conversation_id, state, text, *, image_status=None):
        message = await self.runtime.append_message(conversation_id, "assistant", text,
            metadata={STATE_KEY: state.model_dump(mode="json"), "planner_kind": "guided_system_image",
                      **({"system_image_status": {"project_id": state.project_id, **image_status}} if image_status else {})})
        return {"build_intake": state.model_dump(mode="json"), "message_id": message.id}

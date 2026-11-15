"""Guided requirement intake uses canonical commands and durable revision facts."""
import re

from ..platform.tool_models import ToolInvocationRequest
from ..quality_loop.requirement_review_models import ReviewSelection
from .delivery_dialogue_inputs import read_delivery_intake

STATE = "requirement_intake"


class GuidedRequirementConversation:
    def __init__(self, runtime, revisions, reviews, delivery, projects):
        self.runtime, self.revisions, self.reviews = runtime, revisions, reviews
        self.delivery, self.projects = delivery, projects

    async def handle(self, conversation_id, content):
        conversation = self.runtime.get_conversation(conversation_id)
        if not conversation.project_id or conversation.space_type not in {"build", "project", "version"}:
            return None
        text = content.strip()
        state = next((dict(m.metadata[STATE]) for m in reversed(conversation.messages)
            if m.role == "assistant" and STATE in m.metadata), {})
        if state and state.get("project_id") != conversation.project_id:
            raise ValueError("Requirement conversation scope changed")
        delivery_state = read_delivery_intake(conversation)
        explicit_version = getattr(conversation, "version_id", None)
        if explicit_version and state.get("version_id") not in {None, explicit_version}:
            state = {}
        version_id = explicit_version or state.get("version_id") or (
            delivery_state.version_id if delivery_state and delivery_state.stage == "created" else None)
        add = re.fullmatch(r"(?:需求|新增需求|提交需求|requirement)\s*[：:]\s*(.{1,16000})", text, re.I | re.S)
        select = re.fullmatch(r"(?:重新评审需求|帮我评审需求|评审需求|查看需求评审|review requirement|requirement review)(?:\s+(.+))?", text, re.I)
        answer = re.fullmatch(r"(?:回答|补充|answer)\s*[：:]\s*(.{1,4000})", text, re.I | re.S)
        confirm = text in {"确认评审需求", "confirm requirement review"}
        design = text in {"开始测试设计", "生成测试用例", "准备测试上下文", "start test design", "generate test cases"}
        confirm_design = text in {"确认准备测试上下文", "confirm test context"}
        # Questions and unrelated messages do not consume a pending clarification.
        if not any((add, select, answer, confirm, design, confirm_design)):
            return None
        if not version_id:
            return await self.reply(conversation, {}, "请先在迭代页面选择一个迭代，再提交需求；不会自动使用其他版本。")
        self.delivery.read(conversation.project_id, version_id)
        state = {**state, "project_id": conversation.project_id, "version_id": version_id}
        if add:
            image = self.delivery.read(conversation.project_id, version_id).iteration_image
            draft = {"project_id": conversation.project_id, "version_id": version_id,
                "image_revision_id": image.image_revision_id, "image_artifact_hash": image.image_artifact_hash,
                "title": add[1].splitlines()[0][:200], "text": add[1], "clarification_answers": []}
            result = await self.invoke(conversation, "quality.requirement.revise", draft)
            if result.status != "completed":
                return await self.reply(conversation, state, "需求尚未保存成功，请检查当前迭代和权限后重试。")
            revision_id = next(ref.split(":", 1)[1] for ref in result.result.object_refs if ref.startswith("requirement_revision:"))
            state = {**state, "revision_id": revision_id}
            return await self.prepare(conversation, state)
        if select and select[1]:
            rows = self.revisions.list(conversation.project_id, version_id).items
            choices = [item for item in rows if select[1] in {item.revision_id, item.us_id, item.title}]
            if len(choices) != 1:
                return await self.reply(conversation, state, "请在迭代需求列表中选择要评审的需求，不会猜测需求归属。")
            state = {**state, "revision_id": choices[0].revision_id}
        if not state.get("revision_id"):
            return await self.reply(conversation, state, "请先输入“需求：你的需求描述”，或在迭代页面选择已保存的需求。")
        selection = ReviewSelection(**{key: state[key] for key in ReviewSelection.model_fields})
        view = self.reviews.read(selection)
        if design or confirm_design:
            return await self.test_design(conversation, state, view, confirm=confirm_design)
        if answer:
            if view["status"] != "clarification_required":
                return await self.reply(conversation, state, "当前没有待回答的评审问题。请先查看评审结果，或修订需求。")
            revision = self.reviews.revision(selection)
            questions = view["evaluation"]["payload"]["assessment"]["questions"]
            question = next((q for q in questions if q["blocking"]), None)
            if not question:
                return await self.show(conversation, state)
            answers = [item.model_dump() for item in revision.clarification_answers if item.question != question["question"]]
            answers.append({"question": question["question"], "answer": answer[1]})
            draft = {"project_id": revision.project_id, "version_id": revision.version_id, "us_id": revision.us_id,
                "expected_revision_id": revision.revision_id, "image_revision_id": revision.image_revision_id,
                "image_artifact_hash": revision.image_artifact_hash, "title": revision.title,
                "text": revision.text, "clarification_answers": answers}
            result = await self.invoke(conversation, "quality.requirement.revise", draft)
            if result.status != "completed":
                return await self.reply(conversation, state, "回答尚未保存，请刷新需求状态；不会覆盖其他人的新修订。")
            state = {**state, "revision_id": next(ref.split(":", 1)[1] for ref in result.result.object_refs if ref.startswith("requirement_revision:"))}
            return await self.prepare(conversation, state)
        if confirm:
            if not state.get("command_id"):
                return await self.prepare(conversation, state)
            result = await self.runtime.confirm_tool_invocation(state["command_id"])
            if result.status != "completed":
                return await self.reply(conversation, state, "评审未成功完成。请检查模型和输入，不会将失败结果视为通过。")
            return await self.show(conversation, state)
        if select and (text.startswith("查看") or text.lower().startswith("requirement review")):
            return await self.show(conversation, state)
        if select and (text.startswith("重新") or view["status"] == "review_failed"):
            return await self.prepare(conversation, state)
        if view["evaluation"]:
            return await self.show(conversation, state)
        return await self.prepare(conversation, state)

    async def invoke(self, conversation, tool, payload):
        # Turn message identity keeps workflow retries on the original command.
        user = next(m for m in reversed(conversation.messages) if m.role == "user")
        return await self.runtime.create_tool_invocation(ToolInvocationRequest(conversation_id=conversation.id,
            tool_id=tool, input=payload, initiator_surface="chat", initiator_actor="user",
            idempotency_key=f"requirement:{user.id}:{tool}"))

    async def test_design(self, conversation, state, view, *, confirm):
        request = view.get("test_design_context_request")
        if not request:
            return await self.reply(conversation, state, "当前需求还没有有效的独立确认，或迭代画像已变化。请先完成需求评审；不会使用旧批准生成用例。")
        link = f"/projects/{conversation.project_id}/versions?version_id={state['version_id']}"
        if confirm:
            if not state.get("test_context_command_id"):
                return await self.reply(conversation, state, "请先输入“开始测试设计”，核对本次固定输入后再确认。")
            result = await self.runtime.confirm_tool_invocation(state["test_context_command_id"])
            if result.status != "completed":
                return await self.reply(conversation, state, "测试上下文未保存成功。请检查当前需求批准、画像与来源权限；不会自动重发新命令。")
            return await self.reply(conversation, state, "测试上下文已保存，尚未调用模型生成用例。请打开[迭代测试设计](" + link
                + ")，选择已保存上下文，审核测试范围，再确认模型及预算。用例和脚本仍需独立审核后才能执行。")
        preview = await self.invoke(conversation, "query.system_image.context.preview", request)
        if preview.status != "completed" or not preview.result or not preview.result.context_pack:
            return await self.reply(conversation, state, "无法核验测试设计输入，请检查当前需求、画像和来源权限。没有保存上下文或调用模型。")
        result = await self.invoke(conversation, "system_image.context.compile", {
            **request, "expected_input_digest": preview.result.context_pack.input_digest})
        if result.status != "waiting_confirmation":
            return await self.reply(conversation, state, "测试上下文准备命令尚未进入待确认状态，请打开迭代页查看原命令结果。")
        return await self.reply(conversation, {**state, "test_context_command_id": result.id},
            "将固定当前迭代已确认的需求、完整验收条件、业务规则和代码来源，保存正式测试设计上下文。"
            "\n\n回复 **确认准备测试上下文** 后保存。这一步不调用模型、不批准用例，也不执行测试。")

    async def prepare(self, conversation, state):
        selection = ReviewSelection(**{key: state[key] for key in ReviewSelection.model_fields})
        try:
            preview = self.reviews.preview(selection)
        except (ValueError, PermissionError):
            return await self.reply(conversation, state, "需求已保存，但暂时无法开始评审。请核对当前迭代、来源权限和已启用的真实模型，再输入“评审需求”重试；不会生成模拟评审结果。")
        result = await self.invoke(conversation, "quality.requirement.evaluate", preview["request"])
        state = {**state, "command_id": result.id}
        return await self.reply(conversation, state, f"需求已保存。将使用 **{preview['model']['model']}** 评审当前修订，"
            f"发送需求、已回答问题及 {len(preview['evidence'])} 条选定来源记录。\n\n"
            "回复 **确认评审需求** 后开始。模型会给出待澄清问题和验收条件建议，不会替你批准需求。")

    async def show(self, conversation, state):
        view = self.reviews.read(ReviewSelection(**{key: state[key] for key in ReviewSelection.model_fields}))
        if view["status"] == "clarification_required":
            questions = view["evaluation"]["payload"]["assessment"]["questions"]
            question = next(q for q in questions if q["blocking"])
            text = view["evaluation"]["payload"]["assessment"]["summary"] + "\n\n**需要你澄清：** " + question["question"]
            text += "\n\n" + question["rationale"] + "\n\n请回复 **回答：你的说明**。已保存的回答会带入下一轮评审。"
        elif view["status"] in {"review_failed", "review_pending", "superseded", "image_changed", "draft"}:
            text = "评审尚未形成当前有效结论。请打开迭代需求页检查原命令、最新需求及画像；需要再次评审时输入“重新评审需求”。不会沿用旧结论。"
        else:
            link = f"/projects/{conversation.project_id}/versions?version_id={state['version_id']}"
            text = ("需求已由独立审核人确认，验收条件已保存。可以回复 **开始测试设计**，或打开[迭代测试设计](" + link
                + ")继续。不代表用例执行或质量门禁已通过。"
                if view["status"] == "confirmed" else
                "请打开[迭代需求评审](" + link + ")，查看模型建议、来源和验收条件，由独立审核人逐项批准并确认。当前对话不会代为批准。")
        return await self.reply(conversation, state, text)

    async def reply(self, conversation, state, text):
        metadata = {"planner_kind": "guided_requirement", STATE: {"project_id": conversation.project_id, **state}}
        message = await self.runtime.append_message(conversation.id, "assistant", text, metadata=metadata)
        return {"message_id": message.id}

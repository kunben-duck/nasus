"""Conversation guidance delegates every iteration write to the canonical runtime."""
import re

from ..platform.tool_models import ToolInvocationRequest
from ...domain.system_image.publication import PublicationChanged
from .delivery_dialogue_inputs import (
    DELIVERY_STATE_KEY, DeliveryIntake, DialogueImageBinding, delivery_turn, read_delivery_intake,
)


class GuidedDeliveryConversation:
    def __init__(self, *, runtime, projects, snapshots, publications, delivery_read):
        self.runtime, self.projects, self.snapshots = runtime, projects, snapshots
        self.publications, self.delivery_read = publications, delivery_read

    async def handle(self, conversation_id, content):
        command = delivery_turn(content)
        if command is None:
            return None
        conversation = self.runtime.get_conversation(conversation_id)
        if conversation.space_type not in {"build", "project", "version"}:
            return None
        zh = bool(re.search(r"[\u4e00-\u9fff]", content))
        project_id = conversation.project_id
        if not project_id:
            return await self._reply(conversation.id, "请先创建项目并接入代码，再构建和发布画像基线。" if zh
                else "Create a project and capture code first, then build and review its image baseline.")
        self.projects.get_project(project_id)
        state = read_delivery_intake(conversation)
        kind = command["kind"]
        if kind == "publication":
            # Publication remains an independent, exact-image human review.
            image = self.snapshots.get_system_image(project_id, working=True)
            if image.visibility.mode == "source_filtered":
                raise PermissionError("Full source access is required to review an image")
            link = f"/projects/{project_id}/knowledge"
            return await self._reply(conversation.id,
                ("请先在[系统画像](" + link + ")中选择候选修订，核对来源证据并完成独立发布审核，再确认发布。"
                 "这条消息不会代你批准或发布。发布后回复 **创建迭代**，我会引导你选定基线和迭代名称。") if zh else
                (f"Select a candidate in [System image]({link}), inspect its evidence, complete the independent publication review "
                 "and confirm publication. This message does not approve or publish it. Then say **create iteration** to select a baseline and name."),
                metadata={"delivery_next_action": {"project_id": project_id, "action": "review_publication"}})
        if kind == "status":
            version_id = command.get("version_id") or (state.version_id if state else None) or getattr(conversation, "version_id", None)
            return await self._status(conversation, version_id, zh)
        if kind == "cancel":
            return await self._reply(conversation.id, "已取消这次创建提案，已有迭代不会被删除。" if zh
                else "This proposal is cancelled. Existing iterations are not deleted.",
                state=DeliveryIntake(project_id=project_id, locale="zh" if zh else "en"))
        if kind == "confirm":
            if state and state.stage == "created":
                return await self._status(conversation, state.version_id, zh)
            if not state or state.stage != "confirmation" or not state.image_binding or not state.name:
                return await self._reply(conversation.id, "还没有可确认的创建提案。请先提供迭代名称，并明确选择已发布画像。" if zh
                    else "No creation proposal is ready. Supply an iteration name and explicitly select a published image first.")
            return await self._create(conversation, state)
        if kind == "create":
            # A new explicit create request replaces the draft, not business records.
            state = DeliveryIntake(project_id=project_id, name=command.get("name", ""),
                publication_id=command.get("publication_id") or (state.publication_id if state and state.stage != "created" else None),
                locale="zh" if zh else "en")
        elif kind == "name":
            state = DeliveryIntake(project_id=project_id, name=command["name"],
                publication_id=state.publication_id if state and state.stage != "created" else None,
                locale="zh" if zh else "en")
        elif kind == "select":
            state = (state.model_copy(update={"publication_id": command["publication_id"], "image_binding": None,
                "stage": "selection", "version_id": None, "proposal_id": DeliveryIntake(project_id=project_id).proposal_id})
                if state and state.stage != "created" else DeliveryIntake(project_id=project_id,
                    publication_id=command["publication_id"], locale="zh" if zh else "en"))
        return await self._prepare(conversation, state)

    async def _prepare(self, conversation, state):
        zh = state.locale == "zh"
        if state.publication_id and state.name:
            pin = self.publications.pin(state.project_id, state.publication_id, require_current=True)
            state.image_binding = DialogueImageBinding(publication_id=pin.publication_id,
                image_revision_id=pin.image_revision_id, image_artifact_hash=pin.image_artifact_hash,
                expected_head_id=pin.publication_id)
            state.stage = "confirmation"
            text = (f"请核对：迭代 **{state.name}**，基线发布 `{pin.publication_id}`，画像修订 `{pin.image_revision_id}`。\n\n"
                    "初始基线将固定保存，后续项目发布新画像不会替换它。回复 **确认创建迭代** 后创建；"
                    "这不代表需求、用例或发布质量已经获批。") if zh else (
                    f"Review iteration **{state.name}**, publication `{pin.publication_id}`, image `{pin.image_revision_id}`.\n\n"
                    "Its initial baseline remains fixed even if the project publishes a new image. Reply **confirm iteration creation**. "
                    "This does not approve requirements, cases or release quality.")
            return await self._reply(conversation.id, text, state=state)
        image = self.snapshots.get_system_image(state.project_id)
        if image.visibility.mode == "source_filtered":
            raise PermissionError("Full source access is required to select an iteration baseline")
        choices = []
        for baseline in image.baselines[:20]:
            head = self.publications.history(state.project_id, baseline.id, limit=1)["head"]
            if head:
                pin = self.publications.pin(state.project_id, head["publication_id"], require_current=True)
                choices.append(f"- `{pin.publication_id}` / `{pin.image_revision_id}`")
        text = ("请提供迭代名称，并选择一条已发布画像记录。不会自动使用最新画像。\n\n" if zh else
                "Provide an iteration name and select one published image. The latest image is not selected automatically.\n\n")
        if choices:
            text += "\n".join(choices)
            text += ("\n\n例如：创建迭代 Sprint 1，使用画像发布 <上面的发布ID>" if zh else
                     "\n\nExample: create iteration Sprint 1 using publication <ID above>")
        else:
            text = ("当前还没有正式发布的画像。请先查看候选画像、完成发布审核并发布基线，再创建迭代。" if zh else
                    "No published image is available. Review a candidate and publish its baseline before creating an iteration.")
        return await self._reply(conversation.id, text, state=state)

    async def _create(self, conversation, state):
        zh = state.locale == "zh"
        try:
            # Current-head comparison belongs to the atomic create command. A
            # committed command replay must still work after a newer publication.
            pin = self.publications.pin(state.project_id, state.publication_id, require_current=False)
            if (pin.image_revision_id != state.image_binding.image_revision_id
                    or pin.image_artifact_hash != state.image_binding.image_artifact_hash
                    or pin.publication_id != state.image_binding.expected_head_id):
                raise PublicationChanged("The selected publication changed")
        except PublicationChanged:
            state = state.model_copy(update={"stage": "selection", "image_binding": None, "publication_id": None})
            return await self._reply(conversation.id, "选定的发布头已变化，旧提案已失效。请重新选择画像并确认；尚未创建迭代。" if zh
                else "The selected publication head changed. Select and confirm a new proposal; no iteration was created.", state=state)
        command = await self.runtime.create_tool_invocation(ToolInvocationRequest(
            conversation_id=conversation.id, tool_id="version.create",
            input={"project_id": state.project_id, "name": state.name, "image_binding": state.image_binding.model_dump(mode="json")},
            initiator_surface="chat", initiator_actor="user", idempotency_key="delivery:" + state.proposal_id,
        ))
        if command.status != "completed" or command.result is None or command.result.status != "completed":
            return await self._reply(conversation.id, ("尚未确认迭代创建成功。请核对原命令、权限和发布头；如果选择已经失效，请重新准备提案。不会自动切换画像。" if zh else
                "Iteration creation is not confirmed. Check the original command, access and publication head. Prepare a new proposal if its selection expired; no image is substituted."),
                state=state, metadata={"delivery_command_id": command.id})
        versions = [ref.split(":", 1)[1] for ref in command.result.object_refs if ref.startswith("version:")]
        if len(versions) != 1:
            raise ValueError("Version creation did not return one persisted version")
        view = self.delivery_read(state.project_id, versions[0])
        state = state.model_copy(update={"stage": "created", "version_id": versions[0]})
        return await self._reply(conversation.id,
            (f"迭代 **{state.name}** 已创建，并固定了初始画像基线。下一步是提交并评审本迭代需求，"
             "尚未生成或执行测试，也未通过质量门禁。") if zh else
            (f"Iteration **{state.name}** was created with its pinned initial image. Next: submit and review its requirement. "
             "Tests have not been generated or executed, and no quality gate has passed."), state=state,
            metadata={"version_delivery": view, "delivery_command_id": command.id})

    async def _status(self, conversation, version_id, zh):
        if not version_id:
            versions = self.projects.list_versions(conversation.project_id)
            rows = "\n".join(f"- {item.name}: `{'查看迭代' if zh else 'view iteration'} {item.id}`" for item in versions)
            return await self._reply(conversation.id, (("请选择要查看的迭代，不会自动切换到其他版本：\n\n" if zh else
                "Select the iteration to inspect; no other version is substituted:\n\n") + rows) if rows else
                ("当前项目还没有迭代。请先发布画像，再提供迭代名称并选择发布记录。" if zh else
                 "This project has no iteration. Publish an image, then select the publication and supply a name."))
        view = self.delivery_read(conversation.project_id, version_id)
        return await self._reply(conversation.id, ("以下是所选迭代的实际状态；项目创建、画像发布与质量门禁是不同阶段。" if zh else
            "The selected iteration's recorded state is shown below. Project setup, image publication and quality gates are separate stages."),
            metadata={"version_delivery": view})

    async def _reply(self, conversation_id, text, *, state=None, metadata=None):
        metadata = dict(metadata or {})
        view = metadata.get("version_delivery")
        if hasattr(view, "model_dump"):
            metadata["version_delivery"] = view.model_dump(mode="json")
        message = await self.runtime.append_message(conversation_id, "assistant", text,
            metadata={"planner_kind": "guided_delivery", **({DELIVERY_STATE_KEY: state.model_dump(mode="json")} if state else {}),
                      **metadata})
        return {"message_id": message.id}

"""Recover legacy Build scope from receipts, never from generated prose."""
import re

from ...domain.system_image.source_binding import is_placeholder_source
from .build_dialogue_inputs import BuildIntake


def creation_receipts(conversation):
    result = {}
    for item in conversation.tool_invocations:
        refs = item.result.object_refs if item.result else []
        if (item.conversation_id == conversation.id and item.tool_id == "project.create"
                and item.status == "completed" and item.result and item.result.status == "completed"
                and len(refs) == 1 and refs[0].startswith("project:")):
            result[refs[0].removeprefix("project:")] = item
    return result


def recoverable_project(conversation, content):
    receipts = creation_receipts(conversation)
    if conversation.project_id:
        return conversation.project_id
    selected = re.fullmatch(r"(?:选择项目|select project)\s+(proj_[a-zA-Z0-9_-]+)", content.strip(), re.I)
    if selected:
        return selected[1] if selected[1] in receipts else None
    invocations = {item.id: item for item in conversation.tool_invocations}
    for message in reversed(conversation.messages):
        if message.role != "assistant":
            continue
        refs = [ref.removeprefix("project:") for ref in message.object_refs if ref.startswith("project:")]
        if not refs:
            continue
        if len(set(refs)) != 1 or refs[0] not in receipts:
            return None
        for tool_ref in message.tool_refs:
            item = invocations.get(tool_ref.removeprefix("tool_invocation:"))
            if (item and item.conversation_id == conversation.id and item.status == "completed"
                    and item.result and item.result.status == "completed"
                    and f"project:{refs[0]}" in item.result.object_refs
                    and item.input_payload.get("project_id", refs[0]) == refs[0]):
                return refs[0]
        # An unverified newer scope must not silently fall back to an older one.
        return None
    return next(iter(receipts)) if len(receipts) == 1 else None


class BuildDialogueRecovery:
    def __init__(self, conversations, snapshots, revisions):
        self.conversations, self.snapshots = conversations, snapshots
        self.revisions = revisions

    def status(self, state):
        image = self.snapshots.get_system_image(state.project_id, working=True)
        published = self.snapshots.get_system_image(state.project_id)
        if image.visibility.mode == "source_filtered" or published.read_state.mode == "published":
            return image_status(image, published, state.locale)
        # candidate_revision is only populated on a materialization response.
        # Read durable, ACL-filtered revisions instead of trusting that transient field.
        after_id, historical = "", False
        for _ in range(10):
            page = self.revisions.list(state.project_id, after_id=after_id, limit=100)
            historical = historical or bool(page.items)
            candidate = next((item for item in page.items if image.source_manifest
                and item.manifest_id == image.source_manifest.manifest_id), None)
            if candidate:
                verified = self.revisions.frozen_header(state.project_id, candidate.image_revision_id)
                return image_status(image.model_copy(update={"candidate_revision": verified}), published, state.locale)
            if not page.next_after_id:
                result = image_status(image, published, state.locale)
                if historical:
                    result["summary"] = (("已有历史候选画像，但不对应当前采集版本。\n\n" if state.locale == "zh"
                        else "Historical candidates exist, but do not match the current captured sources.\n\n") + result["summary"])
                return result
            after_id = page.next_after_id
        return {"status": "review_required", "next_action": "review", "summary":
            "画像版本较多，暂未完成当前版本核对。请打开“查看系统画像”选择候选版本；不会据此重复构建。" if state.locale == "zh"
            else "There are many image revisions. Open View system image to select and verify a candidate; no duplicate build will be started."}

    def recover(self, conversation, content, locale):
        project_id = recoverable_project(conversation, content)
        if not project_id:
            return None
        if not conversation.project_id:
            conversation = self.conversations.bind_created_project(conversation.id, creation_receipts(conversation)[project_id])
        image = self.snapshots.get_system_image(project_id, working=True)
        state = BuildIntake(stage="existing", project_id=project_id, project_name=image.project.name, locale=locale)
        goals = [goal for goal in conversation.agent_goals
                 if goal.project_id == project_id and goal.goal_template == "system_image_build"
                 and goal.status not in {"completed", "failed", "cancelled"}]
        if len(goals) == 1:
            state.stage, state.goal_id = "building", goals[0].id
        return conversation, state


def image_status(image, published, locale):
    zh = locale == "zh"
    if image.visibility.mode == "source_filtered":
        return {"status": "restricted", "summary": image.summary, "next_action": "review"}
    code = [source for source in image.sources if source.source_type == "code"
            and not is_placeholder_source(source, image.project.name)]
    captured = image.source_manifest is not None and any(member.source_type == "code" for member in image.source_manifest.members)
    captured = captured and all(member.status == "captured" for member in image.source_manifest.members if member.source_type == "code")
    if published.read_state.mode == "published" and published.read_state.pin:
        status, action = "published", "review"
        summary = ("已有正式发布的系统画像。你可以查看该版本的来源证据；发布不等于测试已经执行或质量全部达标。" if zh
                   else "A published system image is available. Review its pinned evidence; publication does not establish executed tests or complete quality coverage.")
    elif image.candidate_revision:
        candidate = image.candidate_revision
        status, action = "candidate", "review"
        summary = (f"**结构候选画像已生成，但尚未正式发布。** 当前候选包含 {candidate.object_count} 个对象、{candidate.relationship_count} 条关系。下一步请打开“查看系统画像”，审阅候选版本、来源证据和待补充项，再单独确认发布。项目创建任务的“已完成”不代表整个画像流程完成。" if zh
                   else f"**A structural candidate exists, but is not published.** It contains {candidate.object_count} objects and {candidate.relationship_count} relationships. Open View system image to review the candidate, evidence and gaps before a separate publication decision. Completing project setup does not complete the image workflow.")
    elif not code:
        status, action = "source_required", "provide_sources"
        summary = ("**系统画像还没有构建完成。** 项目已创建，但缺少必需的代码来源。请直接发送 Git 仓库地址或已授权的服务端代码目录；需求文档、历史测试用例可以稍后上传，也可以跳过。" if zh
                   else "**The system image is not built yet.** The project exists, but code is missing. Send a Git repository URL or approved server code path. Requirements and historical tests are optional.")
    elif not captured:
        status, action = "sources_pending", "capture_sources"
        summary = ("**系统画像尚未完成。** 已登记代码来源，但还没有完整、可用的采集快照。请检查原地址和访问权限，然后回复 **确认采集已有资料**，我会重试采集并准备构建；不会更换来源或执行仓库代码。" if zh
                   else "**The image is not complete.** Code is registered but capture is incomplete. Check source access, then reply **confirm source capture** to capture the existing sources and prepare the build. This does not replace sources or execute repository code.")
    else:
        status, action = "not_built", "build_candidate"
        summary = ("**资料已采集，但还没有生成结构候选画像。** 回复 **继续构建**，我会使用当前已采集的版本准备构建计划，并展示需要确认的操作预算；无需重新创建项目或上传相同资料。" if zh
                   else "**Sources are captured, but no structural candidate exists yet.** Reply **continue build** to prepare a plan from these captured versions and review its operation budget. No new project or duplicate upload is needed.")
    return {"status": status, "summary": summary, "next_action": action}

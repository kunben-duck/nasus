"""User-facing onboarding copy, separate from workflow decisions."""


def prompt_for(state):
    zh = state.locale == "zh"
    if state.stage == "name":
        return ("可以，我会引导你接入资料，再构建系统画像。\n\n**先给项目起个名字。** 确认名称后，我会创建项目。\n\n接下来需要代码仓库地址或已授权的服务端目录；需求文档和历史测试用例可选，没有也可以先构建。"
                if zh else "I can guide you from source inputs to a system image.\n\n**What project name would you like to use?** I will create it with that name, then ask for a Git repository or approved server path. Requirements and historical tests are optional.")
    if state.stage == "sources":
        if not state.code:
            return (f"项目 **{state.project_name}** 已创建。请提供 **Git 仓库地址或已授权的服务端代码目录**，也可以注明分支或提交 SHA。\n\n如果有需求文档和历史测试用例，可以一起提供或上传；没有的话回复“跳过可选资料”。不要在聊天里粘贴密码或访问令牌。"
                    if zh else f"Project **{state.project_name}** is ready. Send a **Git repository URL or approved server code path**, optionally with a branch or commit SHA. You can also provide or upload requirements and historical tests, or say **skip optional sources**. Do not paste passwords or access tokens.")
        return ("代码来源已记下。**是否还要接入需求文档或历史测试用例？**\n\n可以提供资料地址或上传文件；如果暂时没有，回复“跳过可选资料”，我会先基于代码构建，并明确标出知识缺口。"
                if zh else "The code source is recorded. **Would you like to add requirements or historical tests?** Provide source paths or upload files, or say **skip optional sources**. A code-only image will explicitly report missing context.")
    if state.stage == "review":
        rows = [f"- {'项目' if zh else 'Project'}: {state.project_name}",
                f"- {'代码' if zh else 'Code'}: `{state.code}`",
                f"- {'分支 / 提交' if zh else 'Ref / commit'}: {state.code_ref or ('仓库默认引用' if zh else 'repository default')}",
                f"- {'需求文档' if zh else 'Requirements'}: {state.requirements or ('未提供' if zh else 'not provided')}",
                f"- {'历史测试' if zh else 'Historical tests'}: {state.tests or ('未提供' if zh else 'not provided')}"]
        return (("请核对本次接入范围：\n\n" if zh else "Review the source inputs:\n\n") + "\n".join(rows)
                + ("\n\n回复 **确认接入并构建** 后，我会采集这些资料、固定代码版本并准备画像构建。结构构建的授权会在采集后展示；不会运行你的项目、执行测试或自动发布正式基线。也可以直接告诉我要修改哪项。"
                   if zh else "\n\nReply **confirm and build** to capture these sources, pin the code revision and prepare the image build. Structural execution consent follows capture. This does not run your application or tests, or publish an official baseline. You can also correct any input."))
    return ("资料已经接入，正在推进系统画像构建。进度和需要确认的步骤会显示在对话中。"
            if zh else "Sources are captured and the system-image build is underway. Progress and required confirmations appear in this conversation.")


def goal_summary(goal, locale):
    zh = locale == "zh"
    reason = goal.pause_reason
    if reason == "waiting_confirmation":
        return ("构建计划已准备好，下一步需要你确认下面的操作范围和预算。确认后，我会自动继续，不需要重新发起构建。"
                if zh else "The plan is ready. Review the next operation and budget below. Once confirmed, I will continue the same build automatically.")
    if reason == "structural_candidate_review":
        return ("**结构候选画像已构建。** 代码版本和来源证据已固定；这还不是正式发布的基线。回复“继续分析”，我会检查候选画像的来源关系和知识缺口。"
                if zh else "**The structural candidate is built.** Its code revision and source evidence are pinned, but it is not an official baseline. Say **continue analysis** to inspect source relationships and knowledge gaps.")
    if reason in {"build_completion_review", "reference_candidate_review"}:
        return ("**候选画像已生成，尚未发布为正式基线。** 请查看构建结果、来源证据和待补充项；候选关联不代表已验证的业务覆盖。"
                if zh else "**The candidate image is available, not published as an official baseline.** Review its artifacts, source evidence and gaps. Proposed links do not establish verified business coverage.")
    if goal.status == "failed":
        return ("构建未完成，请查看下面失败步骤的具体原因。修正后可以重试；不会把失败显示为成功。"
                if zh else "The build did not finish. Review the failed step below, correct the cause and retry. Failed work is not reported as success.")
    if goal.status == "cancelled":
        return "构建已取消，已保存的来源和候选结果仍保留。" if zh else "The build was cancelled. Saved sources and candidates are retained."
    return "我正在推进当前构建，可随时询问进度。" if zh else "I am progressing the current build. You can ask for its status at any time."

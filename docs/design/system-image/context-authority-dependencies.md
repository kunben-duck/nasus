# 固定上下文的规范依赖登记

0075 将 ContextPack 使用的原始 AC／业务规则批准版本连接到 0074 规范来源图及 0070 画像成员图。新归档在原事务中登记；历史归档需要独立确认并验证私有原文后补登记。它不批准需求、修改历史 oracle、推进发布或授予生成／执行权限。测试终态见[实施记录](./implementation-progress.md)。

## 数据与所有权

- `system_image_context_authority_roots` 固定原 context 元数据／工件／输入摘要、原 compile invocation，以及本次登记的 invocation、actor、时间、全部依赖的有序摘要与数量。
- `system_image_context_authority_dependencies` 对每条原始 authority pin 保存对象、规范种类、依据摘要、状态、确切规范修订／工件／registration hash，以及所选画像成员的 registration hash。
- `system_image_context_authority_backfill_targets` 是迁移产生的历史待登记清单，只固定原 context 元数据和工件摘要。它不是已验证依赖，也不是批准或执行许可。

规范事实仍由 quality_loop 拥有，上下文仍通过 application port 获取和重验原始批准。基础设施投影只连接已验证的固定事实，不访问私有正文、模型或其他域的 repository；不持有自己的提交／回滚事务。复合 FK 阻止跨项目、跨规范种类和错误 registration hash。

批准和撤回 pin 都固定具体修订；`unapproved` 也作为负向依赖保留，但没有虚构的修订或工件引用。v1/v2 的旧规则语义不自动补成 v3 authority。读取旧包不会因为最新批准头变化而换掉它的原始 oracle。

## 新归档与只读核验

新编译从已经通过工件 hash、完整固定来源重建和原 provenance 检查的归档获取全部 authority pins。每项必须与原 mandatory constraint 的 authority 完全相等，重复、遗漏、不同种类或多余字段均拒绝；不从摘要计数、当前批准头或检索 top-k 推测依赖。

Context 事实、完整依赖、来源及关联锚点和 metadata-only Outbox 在同一 PostgreSQL 事务提交。登记后事件核验失败时，整个事务回滚。MinIO 预写与 PG 不构成分布式事务；未引用对象保留／GC 仍是 P6 未完成项。

正常读取同时核验原 archive、成员／规范历史、每条类型化依赖、完整集合摘要，以及登记对应的正式确认命令。命令的输入、actor（旧 compile 没有 actor 字段时沿原契约）、项目／会话／goal 和工具类型必须一致；历史命令已终态或确认已过期不使原事实失效。当前权限仍即时检查。

新归档缺登记是损坏，返回脱敏 502；不会通过读操作、新普通写入或事件重放修复。历史待登记包的读取及列表返回明确的 `context_authority_registration_required` 409。后续规范撤回保留原包，但当前使用仍标 stale。登记本身不消除 stale。

## 历史迁移与正式入口

0075 DDL 显式定义三张追加式表和固定 FK／索引。迁移只读取旧 PG 元数据并完整核验摘要，再登记待处理清单；不访问 MinIO／网络，不根据当前 authority 猜旧版本。错误元数据连同 DDL 回滚，存在登记或待处理记录时禁止破坏性降级。

只读发现接口：

```text
GET /v1/projects/{project_id}/system-image/context-authority-backfill?after_id=&limit=3
```

当前 qa_lead／project_admin／platform_admin 可以发现待处理包。默认三条、最多五条 keyset 分页，原游标及包含 look-ahead 的每个归档都重新授权并验证。响应只返回确切登记请求、画像 pin 和需要独立确认的状态，不返回原文、oracle、私有地址、总数或执行许可；`Cache-Control: private, no-store`。任一归档无权、损坏或与待处理元数据不一致时整页拒绝，不返回部分 ID 或游标。

canonical 只读入口 `query.system_image.context.authority_backfill` 使用同一 application use case。严格类型化的 `context_authority_backfill` 回执固定请求、完整有界页、页摘要和下一游标；generation／execution 均未授权。Agent 展开时重新核验当前 reviewer、来源权限、原归档和完整页，一项补登记或页内容变化即使旧回执失效。工具可推荐逐项登记，但查询不创建批准、依赖或确认。

正式写入口是 `system_image.context.register_authorities`，输入固定 `project_id/context_id/artifact_hash/policy_revision=nasus.context-authority-dependencies.v1`。必须走 ToolInvocationRuntime 的独立用户确认；提交时当前 reviewer 身份、精确 actor／请求／会话／goal 和 15 分钟非未来确认重新检查。项目及来源 ACL 锁内再次回读原始归档，完整验证固定来源、规范及原图，不以新 head 替换。

只有匹配迁移清单的原包可首次补登记。已登记包只核验并返回，不追加重复事实或事件；损坏的新包不能冒充历史迁移对象。登记改变的是新的 root，不改原 context、oracle、image、source、规范或 0068／0070–0074 摘要。Outbox 事件只能核验匹配的完整 count／hash／command，不能补造依赖。

## Portal 独立补登记队列

知识页提供独立的历史上下文依赖队列，不依赖发布 head、模型出口或生成任务权限。默认收起，只有用户展开才查询；身份重新核验期间不展示旧队列。每页三项，用户选择原 context／画像／工件 hash 后，必须勾选独立确认才能提交。

提交先重新读取并校验当前页中的原选择，再创建 `system_image.context.register_authorities`，仅在收到匹配的 waiting_confirmation 请求后确认同一命令，完整核验最终 invocation／tool／context 引用。同步防重复提交，不自动重试未知写入结果。保存、刷新、换页、切换身份或页重新核验均使原确认失效；保存成功刷新队列，但不修改历史包或撤回后的 stale 状态。

权限错误、归档错误、响应契约错误或写入结果不明时隐藏受保护记录，要求显式刷新、查看结果并重新确认。默认复用既有深浅色 token、细边框和移动端换行；不增加供应商、ORM 或原文渲染依赖。完整自动维护、统一派生 DAG 和最终性能门禁仍未交付。

## 验证范围与剩余链路

真实 PG 测试覆盖 approved／unapproved、批准撤回后的历史、明确迁移补登记、跨项目 FK、append-only、DDL 一致性、原子失败、坏 archive／缺依赖拒绝和 reviewer 权限。实际双提交 exweb 使用固定 Git blob、PG 和 MinIO 验证来源更新及 SSE 保留期清理后的原版本。

伴随需求、测试、oracle 和 reviewer 是显式合成协议资料，不是 exweb 维护者 business gold；没有外部模型调用或目标执行。小选择集或已归档 CBM 图不替代真实模型精度、provider 对照、容量或性能门禁。

这是当前 ContextPack 到规范事实的类型化连接，不是全项目统一 delta DAG。publication、检索 generation／trace、脚本／RunPlan、原子增量／自动维护、overlay／合并／回滚、其余四用途及旧链切换、动态 Agent 调查／预算、Provider 生命周期／对照／gold／隔离、真实受控执行反馈和完整 V1 仍按完整 P0–P6 交付。开发业务数据库未迁移，开发监督服务未启动；隔离验证不表示上线。

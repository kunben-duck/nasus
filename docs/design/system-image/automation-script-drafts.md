# 固定用例脚本草稿与独立审阅

更新：2026-10-13。0098、0099 在质量域新增原生模型脚本草稿与独立审阅后端，0122 让新生成消费独立用例准入。它不读取旧可变工作区；生成、接受审阅均不授权目标执行。五用途上下文、完整 RunPlan、真实覆盖和 [P0-P6 验收](./delivery-and-evaluation.md)仍是必需交付。

## 固定输入与模型出口

`AutomationScriptGenerationApplicationService` 通过 application ports 回读[自动化输入](./automation-input-preview.md)。选择必须固定 project、mapping revision/hash 和明确 case IDs，并保留原 context/scope/generation/mapping、全部测试义务、每个步骤和独立 oracle。目标 URL、最新资产包或模型自行声明的覆盖不能替代这些输入。

新生成还必须显式固定 `case_approval_revision_id / case_approval_artifact_hash`。
0122 通过独立准入 port 核验同一完整 cohort/basis 和当前 approved head；映射
接受不能代替准入。准确 pin 纳入 call plan v2 和用户确认，且 reservation 通过
PG 复合 FK 连接同项目、同生成批次的审批记录。撤回后禁止新预览/模型出口，
调用后撤回保留原预留而不重发。旧工件不添加字段、不重写 hash，只允许重新
授权的历史读取，缺准入时 `input_current=false`。这不把 blocked 预览晋级为
正式 automation ContextPack，也不替代框架/定位/fixture/compile/collect 门禁。

模型使用经过测试的自定义 chat 配置，预览固定配置摘要、实际目的地址、完整消息摘要、来源绑定与当前权限 fingerprint、operator tokenizer/价格政策、token/费用上限。当前一次调用处理完整有界输入，不截断用例或义务；费用是政策上限而非供应商发票。预览不发送源码，新的正式生成需要管理员通过 canonical 工具独立确认该精确请求。

PG 在模型调用前保存追加式 reservation、真实 command/actor、generation/mapping 外键和调用 ID。响应保存 native usage、实际 `LLMCall` 与私有 MinIO 原文，之后验证 DSL 并原子提交草稿、审计和 metadata-only Outbox。结果未知或缺少原生 usage 时保留 reservation，不自动重发；无效 DSL 可保留有效调用回执，但没有草稿或执行权。已归档回复的内部重放不会再调用 Provider；独立公开恢复、Temporal 生命周期、取消和 owner fencing 尚未接入这条脚本路径。

## 脚本与断言

草稿只允许显式 browser 或 HTTP DSL，不接受 JavaScript、shell、SQL 或任意工具代码。每个选中用例必须恰好有一个脚本或明确 gap，每个原步骤都要有绑定；所有原 oracle 保持内容与摘要，且分别绑定到真实 DSL assertion action。新增无独立 oracle 的断言、混用动作族或遗漏测试义务均拒绝。

HTTP 请求使用 target-relative path，request ID 必须唯一，断言只能引用前面的请求。JSON operands 拒绝重复键和非 JSON 常量；request headers 只允许 Accept/Content-Type，不接受 Authorization、Cookie 或 Host。浏览器定位器与 HTTP 路径仍是待核验草稿，不因通过 schema 就证明目标上有效。业务预期与脚本判断是否语义等价仍需要审阅，schema 不能代替业务证据。

默认旧请求仍使用 proposal v1，不增加新的默认字段。明确选择 [HTTP v2 响应资源绑定](./http-response-bindings.md)后，原请求、模型消息/预算摘要和 proposal v2 固定此协议；变化必须重新确认。capture 逐项保留原步骤和独立审阅，不成为断言或业务答案。结果/native-reply/review 的原 envelope 保留，历史按保存时的明确协议重验；不存在根据模型回复自动升级的路径。

草稿固定原输入、实际调用、原始响应摘要和派生 proposal。PG 表为 `quality_automation_call_reservations`、`quality_automation_native_replies`、`quality_automation_script_revisions`，私有对象按项目和内容摘要归档。读取重放原来源/上下文/用例映射并重新授权；模型配置随后变化不重写原结果。历史保留与当前可用状态分离，撤回 scope/mapping 后历史仍可授权读取，但不能用于新生成或执行。

0100 增加[脚本与审阅派生追溯](./automation-provenance.md)，在原事务连接 context/scope/generation/coverage/mapping 和全部选中 case 的原工件及登记摘要。审阅另固定原脚本与完整前驱，普通读和事件重放只核验，不修补缺失历史。它不改写上述事实或旧 v1 依赖图，也不形成执行许可或完整项目 delta DAG。

## 追加式独立审阅

审阅通过脚本读取 port 消费固定草稿，不修改原脚本或 planned CoverageMatrix。每个 DSL action 固定 `(case_id, action_index, action_digest)`，每个断言固定 `(case_id, row_id, action_index, source_step_index, oracle_digest)`。全部动作和断言必须恰好出现一次，逐项选择 accept/reject/defer 并给出理由；只有无 gap 且全部接受才是 `review_complete`。

审阅保存原 script/input/proposal hash、context/scope/generation/mapping pins、实际 reviewer/command、策略和确切前驱。0099 的 `quality_automation_script_reviews` 保存元数据，私有 MinIO 保存完整决定。项目锁、实时角色与来源授权、15 分钟且非未来的实际确认、前驱 CAS、事实/审计/Outbox 同事务，防止另一命令覆盖当前 head。历史回读不持有旧命令的写锁，新命令提交仍锁定；正常读取不修补损坏历史。

拒绝或暂缓不算完整接受，撤回只追加到当前 reviewed head。输入失效后可以撤回旧决定，但不能新审阅。审阅阶段独立于生成；当前政策允许有 reviewer 权限的生成者参与审阅，尚不强制两个不同账号。固定 exweb 专项实际使用另一 qa_lead 账号，仅证明该路径可用，不代表政策已强制职责分离或维护者业务批准。

无论接受或撤回，`execution_authorized=false`，automated/executed_on_target/passed 均为 0。完整接受仍需目标 build/environment、API/DOM locator 证据、fixture/setup/cleanup 和 immutable RunPlan；不能仅改计数或 boolean 获得真实覆盖。

## 正式入口

工具通过 `ToolInvocationRuntime` 保留权限、确认和审计：

| Tool ID | 行为 |
| --- | --- |
| `query.quality.automation_execution` | 无模型出口的固定输入/预算预览 |
| `query.quality.automation_history` | 固定原映射的有界只读命令历史，重新授权，不授予生成或执行许可 |
| `quality.automation.generate` | 精确预览请求的管理员独立确认与原生草稿生成 |
| `query.quality.automation_review` | 无正文、需再次核验的当前审阅回执 |
| `quality.automation.review` | qa_lead/admin 的完整动作/断言审阅或撤回，独立确认 |

HTTP 仅提供预览和读取，响应 private/no-store：

```text
POST /v1/projects/{project_id}/quality/automation-script-previews
GET /v1/projects/{project_id}/quality/automation-script-history?mapping_revision_id=...&mapping_artifact_hash=...&after_id=&limit=10
GET /v1/projects/{project_id}/quality/automation-script-revisions/{revision_id}
GET /v1/projects/{project_id}/quality/automation-script-revisions/{revision_id}/review?artifact_hash=...
GET /v1/projects/{project_id}/quality/automation-script-reviews/{revision_id}
```

没有导入结果、直接保存脚本或直接批准的 HTTP 入口。回执再被 Agent 使用时重新检查项目、权限、完整工件和审阅头；来源失效或历史变化不能沿用旧回执。事件只发送 ID、状态、计数和查询键，不暴露私有对象地址、源码、原始模型回复、审阅正文或密钥。

## 命令发现与 Portal

2026-10-13 新增显式 HTTP v3：公共生成、完整独立 action/oracle 审阅、RunPlan v3
及 build binding 的范围与旧摘要兼容见[Fixture 业务资源绑定](./run-plan-fixture-bindings.md)。
导入是资源声明而非 oracle；持久业务执行仍需原 setup 的完整私有 handoff，不能
仅凭 v3 proposal 或接受审阅进入 claim／dispatch。

历史查询固定原 mapping revision/hash，按 canonical command ID 分页，每页最多 20 项。即使空页，也重新回读完整原自动化输入并核验来源权限；结果及 look-ahead 的预留、原生回复和草稿归档均重新核验。完成命令缺少草稿时拒绝返回，预留而无原生回执的调用明确保持 outcome unknown。该查询不重发模型、不修改预留，也不是取消或恢复执行器。Agent 再次使用查询回执时重新读取原页，历史发生变化返回 409，不把新记录静默接入旧观察。

Portal 已有默认折叠的脚本生成和独立审阅组件。展开后读取历史；全部历史页加载、没有 running 调用、原输入当前有效且选择经过测试的模型后，才能预览用户填写的单次 token/费用上限。确认绑定完整原输入、模型、预算和观察版本；字段变化使确认失效。提交经过 canonical invocation 与一次显式确认，失联后只读查询原命令，不自动重发。

审阅默认逐项暂缓、理由为空，全部 DSL action 与原 oracle 分别选择决定并填写理由。支持原 head 的独立确认、历史选择和追加式撤回；确认后修改理由必须重新确认。查询异常、错 pin 或撤权隐藏受保护的父级草稿。脚本输入与相邻只读输入预览使用独立 query key，关闭面板不会因相邻缓存错误锁住导航。正文以 React 文本节点展示，沿用共享深浅色 token、移动布局和无可见滚动条体验。

Portal 消费原生调用预留、回复归档、草稿提交与独立审阅事件；不要求前三种事件附加 `snapshot_hint`。既有事件 ID/version 去重、200ms 合并、当前工作区范围与查询是否已挂载的检查仍生效。上游上下文失效和映射审阅同时刷新脚本输入、历史与审阅查询；这些事件不自动生成、恢复或执行脚本。私有读取权限仍由后端重新核验，客户端刷新不是访问授权。

浏览器修复批已在隔离 PG/MinIO 完成四项交互测试，两种主题均通过；动态翻译加载及控件标签重新索引的原失败保留在[实施记录](./implementation-progress.md)。协议夹具只验证交互，不是原生外部模型、网络 SSE 或目标运行。390px 的多层表单挤窄已有独立红/绿证据：理由控件宽度从 146px 改为至少 220px，顶部动作控件高度不超过 36px，两种主题的四项专项通过；这不是完整移动可访问性验收。旧 `automation.generate` 尚未切换到这条正式链，完整 UI 和生命周期仍以实际门禁为准。

## 验证与剩余门禁

原生 HTTP Provider adapter 的 MockTransport specimens 验证真实 wire、canonical confirmation、PG 外键/追加式约束和私有 MinIO，不声称外部模型或维护者批准规范。固定 exweb 使用原 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`，核验全部 126 个 Git blob 和 725 个固定代码成员；另有 Orders 代码及需求/oracle 协议夹具，与 exweb 业务目标分开记录。具体终态和失败见[实施记录](./implementation-progress.md)。

继续要求完整脚本生命周期与 UI、automation ContextPack、locator/AST/compile/collect 证据、case/step/oracle/script/build/environment/fixtures 的正式 RunPlan、canonical 真实目标执行及业务覆盖/发布回流。自动 delta/overlay/merge、五用途/旧链切换、独立 gold、多语言、安全、容量/性能和原 P0-P6 不缩减。

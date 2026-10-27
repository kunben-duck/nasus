# 系统画像知识、版本与上下文契约

状态：2026-09-09 目标设计，尚未实现的 schema/API 均为 proposed。主方案见[自主系统画像](./autonomous-system-image-design.md)。本文件定义开发必须遵守的语义；不要求照搬示例表名覆盖现有兼容 DTO。

## 1. 领域边界与数据所有权

```text
interface (HTTP / SSE / MCP-facing Nasus tools)
    -> application use cases -> domain policies
                    <- infrastructure port adapters

AgentGoal -> ToolInvocationRuntime -> SystemImage use cases
                                   -> Source / Code / Document / Retrieval ports
QualityLoop use cases -> SystemImage ContextQueryPort
QualityLoop facts -> outbox -> SystemImage evidence projection
```

system_image 拥有 binding、source/image revisions、结构事实、断言与知识关联；quality_loop 拥有正式 US、AC、用例、脚本、Run、ReleaseDecision。画像里的历史需求/测试是来源投影，新生成 US/测试先走 quality_loop 的治理，再以事件回流，不能两域各建一个可变 US 主表。

0050 已交付来源固定的正式 AC 独立批准与撤回入口，实际契约见[需求批准](./acceptance-authority.md)。0052 新增独立的[业务规则批准](./business-rule-authority.md)，不把规则存成 AC，也不修改来源投影或旧关联的 authority。0051 新增[固定测试设计 ContextPack](./context-packs.md) 的预览、归档与历史重放，v3 接入独立规则批准；仍是 draft investigation，不代表正式 US authoring、BehaviorSpec、五种 ContextPack 和下游生成已完成。

0057 新增固定 ContextPack 的[测试设计范围审阅](./test-design-scope.md)：独立风险、权限、状态、不变量、正反例及显式缺口，仍不授予生成或执行许可。原 ContextPack 不改写，下游新生成/coverage 提交链仍需交付。

后续[生成契约预检查](./test-design-generation.md) 已消费固定 context/scope、保留完整义务并校验模型候选 DTO，能推导 planned CoverageMatrix。0058 增加可信执行器内部的 MinIO 结果归档、PG 草稿用例/coverage/审计/Outbox 原子提交与重新授权的历史读取；0059 增加完整单次原生调用、operator tokenizer/价格策略、确认预算、持久预留、私有响应归档及 canonical 生成入口。0060 接入 [Temporal 任务、取消和单次显式终态恢复](./generation-jobs.md)，原失败命令不重开，已归档响应恢复不重发模型。0063/0064 后续接入完整多调用预算、原生回复、v3 全量归并、共享 canonical/Temporal 与 Portal 确认及历史；0065 增加独立多批恢复的 v4 原子结果、追加式权威关联及共享命令/worker/Portal 输入。私有恢复、公共 canonical 恢复及真实 Temporal 专项已有终态证据，固定 exweb 恢复、独立映射和最新完整 E2E 的当前状态见实施记录；不以此声明容量/性能或完整 P5 完成。旧生成链切换仍未交付，草稿归档不等于独立映射批准或已执行覆盖。

0061 增加[草稿断言的独立映射审阅](./test-design-mapping.md)。审阅固定 generation/context/scope、每个 case/row/step/oracle 和前驱，另存追加式决定，不改写原 draft/planned CoverageMatrix。接受映射不授予来源规范批准、自动化或目标执行权限。项目级 reviewer 草稿发现接口和独立 Portal 队列检查当前角色、原始来源权限及归档完整性，不需要管理员模型出口或生成任务权限。canonical `query.quality.test_design_review_drafts` 返回分页 ID/digest 回执；Agent 再次使用时必须回读重新授权，回执不包含正文或执行权威。各批验证范围与尚未完成项以实施记录为准。

0121 新增独立的用例准入前置环节，不把映射接受直接当作“用例已批准”。
`quality_case_approval_revisions / quality_case_approval_members` 固定同项目、同生成批次的
明确用例集合、原 case/oracle 摘要以及 context/scope/generation/mapping/input pins。
`quality.test_design_cases.review` 是唯一正式写入口，须由当前 qa_lead/project_admin/
platform_admin 独立确认；PG 时间校验 15 分钟确认窗口，并对 cohort 审批头做 CAS。
批准、撤回均追加，原草稿和计划覆盖不修改，历史数据不自动晋级。

只读 `/v1/projects/{project_id}/quality/test-design-case-approvals/preview` 返回完整
原输入与 `input_current`、当前审批头、历史数量；超过完整读取预算则拒绝，不截取用例。
`/{revision_id}` 展开固定记录并核验完整审批链及私有归档。当前输入失效时仍可检查
或撤回原批准，但不能新批准；同命令恢复只返回原事实，不重新启用或改写旧归档。
每次访问和该类 SSE 重放重新检查原来源权限，事件只包含不透明 ID 和批准状态。
Portal 知识页提供独立准入面板，确认绑定完整 pins、审批头和当前读回；失败只允许
显式重新读取，不自动重发写入。

0122 已让新脚本预览与模型出口消费当前独立准入：显式 revision/hash 固定完整
basis，并纳入 call plan 和同项目/同 generation 的 PG FK。旧归档不自动补准入，
只读且当前不可用；撤回后不重发模型、不修改原草稿和覆盖。
这不是正式 `automation` ContextPack，脚本仍仅生成草稿，不授权目标执行或
已验证业务覆盖。正式 automation 消费者还须绑定 framework/API-DOM 定位、
fixture/setup/cleanup、密钥与网络限制；
其他四用途、旧链切换、自动增量、容量和完整 release 闭环仍按原 P0-P6 目标交付。
当前代码及专项验证边界以实施记录为准，不以表或 UI 存在声明完整 P5 完成。

agent 拥有目标、计划、步骤与短期记忆，平台拥有认证/策略/审批/工具调用/审计。各域通过 use case 或明确 DTO/event 协作，不跨域写 repository。领域类型不可 import ORM、LangGraph、Temporal、供应商 SDK；composition 组装实现。

0062 为现有生成/恢复提供 PG worker fencing；0063 新增[完整分包预算与逐调用回执](./generation-batch-ledger.md) 的持久化基础，不复用外部 Provider ID、不伪造合并调用，也不改写原草稿权威。0064 增加 v3 aggregate result、逐调用 FK 和完整草稿/coverage 原子提交；0065 的 v4 恢复关联使用独立新命令，完整回读所有原生回复，不修改失败来源历史。共享 Tool/Temporal/Portal 的当前验证状态见实施记录；旧链切换和完整闭环仍未交付。

0076 增加[历史知识画像回滚](./image-rollback.md)：固定原 publication 与当前 head，独立回滚政策/批准、追加式新发布和原子 CAS。它不要求旧 manifest 成为最新 source，不恢复撤回的业务 authority，也不复活旧索引/上下文当前使用权限；原事实和旧摘要不变。完整自动增量、overlay、合并及五用途仍待交付。

0077 增加[发布与上下文依赖登记](./publication-provenance.md)：原生审阅、批准发布、前驱和回滚源连接固定对象/关联来源根，v4/v5 上下文连接原 publication 登记 hash。事实、登记、审计和 Outbox 同事务，正常读/恢复/事件重放只验证、不修复历史。固定元数据可按操作复用只读快照，但当前启用发布头、ACL 与 authority 仍实时复查；完整检索/脚本/RunPlan 依赖和项目自动增量继续待交付。

## 2. 最小持久化模型

2026-10-07 新增[固定目标的 BuildIntent v3](./targeted-build-intents.md)：计划保存前固定目标 baseline/version、明确已核验的 nullable publication head/image hash 和完整 source binding scope；canonical 保存、结构授权/预留/提交及同目标补源阶段重新验证原目标。v1/v2 digest 与历史不改写，Portal 新计划要求显式选择目标。它补齐目标契约，不代表完整引导/自然语言/维护事件统一、全计划多能力预算或 P2 完成。

2026-10-08 的已保存意图 UI／显式聊天入口共用 application 编译 port，保存的 project/plan/digest 固定为原 Goal 引用；预算、调查及发布仍独立确认。错误摘要或混入指令只澄清，失联只读恢复不重发写入。该共享入口不替代完整自然语言构建、维护事件、跨进程创建幂等和本契约的 P0-P6 验收。

同日新增[固定来源的构建入口与缺码恢复](./source-pinned-build-entries.md)：当前项目的有界中英文请求与 Project Overview 引导共用固定 request/compiler；缺少代码时保留原 target、等待 digest 和一条无模型的本地状态查询。补齐后在同一 Goal 追加 canonical plan，原 checkpoint 消费不能释放独立结构预算；前端回读原状态与保存回执。它不是任意自然语言解析、维护事件、旧链 cutover 或完整 P2 完成。

0089 的[Agent 主动运行预算](./agent-active-runtime.md)为新目标持久累计运行态区间，等待输入/确认不耗时，原目标恢复不清空消耗。旧记录不倒推回填，旧 JSON/v1 digest 保持不变；新 v2 checkpoint 固定计时字段。计时不能授予执行或模型出口权，也不替代累计费用、全局 owner fencing 和完整恢复事务。

0092 增加新构建 Goal 的累计工具工作上限：`image_build_tool_budgets` 在创建 Goal 的同一 PG 事务固定原提案或输入的 limit、scope 和 hash，`image_build_tool_consumptions` 固定每个实际 canonical command 的输入摘要、work identity、sequence 与前驱 hash。运行时在权限检查、命令 claim 后且 handler 执行前，锁原 Goal 核验完整账本，再将预留、脱敏审计和 Outbox 同事务提交。等待确认不预留，同一命令重放不重复扣减，独立新 attempt 占新额度；补源和新阶段共用原上限，不能借新 plan 重置。耗尽或历史不可核验时在 `build_tool_budget_review` 暂停，已有工件保留。旧 Goal 无 pin 时保持未计量，已标记新 Goal 的账本丢失则拒绝，正常读取不修补历史。字段和两表为追加式，降级不能丢弃已存在的预算历史。

该账本统计 Goal 步骤中 plan 读取、授权等控制工具及业务工具，以及显式绑定同 Goal 当前 plan 的独立确认调查；并非项目里所有写动作都自动归入 Goal。后续同目标手动 `build.plan.revise` / `build.plan.activate_revision` 也纳入同一预留：在原 Goal 锁下核验原展示 checkpoint、确认账号/时限、根计划及当前修订/阶段头，不能通过按钮入口漏计或绑定其他目标扣减。等待确认不扣减、同 command 重放不重复扣减，耗尽不执行 handler；若已 dispatch 后业务事务失败，这项工作仍已消费。预算预留和业务事实不是统一交付事务。手动来源采集及其余能力仍未纳入此协议，停止/取消不被新增控制名单阻断，完整覆盖仍待交付。原生 Worker 重试同一 canonical command 仍是一项工具工作，不代表一次 Provider 调用或费用；工具已完成、AgentStep 等待独立审阅而 blocked 时仍算已消费。提案只提供 guardrail，不是执行/模型出口授权；结构 grant 仍独立确认，当前生命周期可能先预留结构 grant 再被累计工具上限拒绝，但不 dispatch handler。预规划/embedding/rerank、模型费用与各能力独立审批尚未统一核算；没有公开预算查询/UI，也不把私有完整性核验当作业务访问授权。完成报告仍保留 `full_plan_accounting_verified=false` 和全预算阻断，真实 Temporal/原生 exweb 的实际验证范围以[实施记录](./implementation-progress.md)为准。

同日新增[构建完成条件评估](./build-completion-assessments.md)：原调查、计划、Goal 检查点和分析摘要固定，全部纳入来源文件字节及完整成员证据重新验证，canonical 回执展开重新授权。完成审阅的普通继续不改变已结算时间或检查点。后续 0090 将每个代码来源实际返回的分析、完整观察和参与合并的原生 generation/projection/协议 pin 绑定到结构候选提交事务；v2 评估自动发现并完整核验，不用另一份同源分析替代。旧工件不补造回执，损坏和缺失拒绝重放。0091 补充独立确认、完整缺口清单和前驱 CAS 的追加式责任修订；审计和 Outbox 原子提交，原报告与 Goal 不变，所有缺口仍 unresolved。后续 v3 通过同一工具显式引用原 v2 和确切已确认责任修订，保留全部原事实，只消除尚未分配责任的合成阻断；当前创建核验成员有效性，历史重放不跟随改派或最新头。Portal 创建后仅 GET 恢复原命令和重新授权。v2/v3 仍是 blocked 评估，不是完整候选交付；全计划累计费用、关键冲突、缺口解决、Goal 原子交付和完整 Portal 引导继续待实现。

0088 的[持久启动回执](./agent-goal-start-receipts.md)固定实际 Temporal workflow、原始请求摘要、会话/项目和 Goal，与创建同一 PG 事务；竞争者不改绑 controller，已暂停/终态的同 workflow 重试不再次启动图。pending/running 的启动重放仍要求独立执行恢复，不以该记录声称公开 Idempotency-Key、dispatch outbox、完整 owner lease 或创建/审计/Outbox 原子链已完成。

0084 增加[固定画像证据调查修订](./evidence-investigation-revisions.md)：调查固定原 plan/goal/image/hash，保存实际证据 pins、问题/缺口和有界只读建议。原结构 goal 可显式继续至独立调查确认，不重新采集或发布；保存历史并三次无新增证据暂停。它不产生业务 authority、语义批准或真实覆盖，也不替代完整跨源关联与全计划预算。

原调查成果的只读 Portal 审阅还要求请求执行时的路由范围校验：URL 切换可能早于 React 旧查询卸载，不能仅依赖 enabled=false。路由层提供当前项目／非审阅范围的回调，领域查询在请求前与返回前检查，并传递 AbortSignal；旧会话 ensure 不得在审阅 URL 下 POST，整图、release、解释、记忆与 Swarm 不得借焦点恢复或 SSE 延迟队列重新读取。SSE 保留原 Conversation 消息和快照刷新，但在派发及二次刷新前重验领域读取范围。固定原报告／画像读取、来源 ACL 和独立发布确认仍沿用原契约，不把这些客户端限制当作后端授权。

0085 增加原用户快照预条件与 `agent_resume_consumptions`：结构继续的全步骤条件写入和原 digest 消费同一 PG 事务，回执仅包含 scope/hash，不保留私有 DTO；贯穿 Temporal 的五字段 pin 防止旧继续请求释放新确认。普通 goal 写、其他恢复分支、治理确认及事实/审计/Outbox 尚未统一原子化，回执不是业务 authority 或执行许可。详见[原目标恢复契约](./evidence-investigation-revisions.md#用户快照与持久消费回执0085)。

0086 增加[同目标补源计划修订](./build-plan-revisions.md)：独立确认后，将新 source manifest、原 goal checkpoint 和完整父修订链固定到追加式草稿 ledger；不覆盖已有 captured 来源、原步骤或工件，不复制旧授权。0086 本身不接入执行阶段，后续接入见下段 0087；保存修订不代表新增资料已建立语义关联或自主构建已完成。

0087 后续增加[原目标的追加式构建阶段](./image-plan-phases.md)：确认修订阶段后目标仍暂停，显式继续只准备独立预算 gate，再确认才执行新计划的结构构建。完整旧步骤/prefix、原目标/version、修订/manifest 和每阶段合同由 PG ledger 核验，旧授权不能转移。Local/LangGraph PG、真实 Temporal Worker 替换/Activity 重试及原生 exweb 有各自专项证据，不是完整 Temporal 恢复、多能力授权、累计费用或 P2 完成证明；新增资料的语义关联/批准仍走独立流程。

所有 tenant 数据必须带 project_id；未来租户隔离字段可新增，不在本轮虚构当前已有 tenant 系统。ID 使用 Nasus 分配的不透明 UUID；跨项目引用在事务内校验。时间用 UTC；revision/manifest 决定版本，时间只描述记录与业务有效期。

| 聚合/记录 | 必需字段 | 不变量 |
| --- | --- | --- |
| SourceBinding | binding_id, project_id, kind, connector_kind, external_identity, tracked_ref, credential_ref, scope, policy_revision, enabled | 同 kind 可多个；外部身份而非 source_type 唯一；凭据不进知识文本 |
| SourceRevision | source_revision_id, binding_id, external_revision, parent_refs, manifest_ref/hash, acquired_at, file_count, excluded/failed_paths, status | 成功快照不可修改；Git pin commit，上传 pin object version/hash；无上游版本用内容 manifest hash |
| SourceManifest | manifest_id, sorted binding/revision pairs, code_build_ref?, assembly_policy_version, hash | 一个 ImageRevision 的跨源组合，不要求文档与代码同一时间，但必须记录适用关系和不确定性 |
| EntityIdentity | entity_id, project_id, kind, source_binding_id?, created_at | 稳定身份不含 provider、绝对路径、行号或 revision |
| EntityRevision | entity_revision_id, entity_id, source_revision_id?, locator, normalized_payload_ref/hash, extraction_version, provenance_id | 状态/文本/位置变化产生新修订；代码行号是定位元数据不是 ID |
| Assertion | assertion_id, subject_revision_id, predicate, object_revision_id/value_ref, semantic_kind, status, evidence_ids, method, decision_id? | expected/observed/hypothesized 分离；结构观察和业务规范可并存 |
| Evidence | evidence_id, source_revision_id/run_id, locator, snippet_hash, object_ref, extractor_version, captured_at, access_scope | 引用精确且可校验；不得只有不可解析的自由文本 evidence_refs |
| LinkDecision | decision_id, assertion_id, accept/reject/defer, reviewer_actor, reason, evidence_digest, policy_revision, recorded_at, applicability | 人工决定不可被自动批覆盖；端点换修订时必须重新验证适用性 |
| Gap / Conflict | id, scope, type, severity, required_for[], evidence_refs, alternatives, owner?, status, resolution_ref? | 缺口是正式可追踪对象，unknown 不用 0 填补 |
| ImageRevision | image_revision_id, baseline_id, parent_revision_id?, manifest_id, overlay_digest, policy_version, status, readiness_ref | candidate 冻结后不可就地修改，修复生成新 candidate |
| ImageMembership / OverlayEntry | image_revision_id, entity_or_assertion_id, revision_or_decision_id, operation, evidence_digest | 持久化逐项准入/替代/tombstone；unique(image_revision_id, kind, item_id)，不是查询时连接“最新批准状态” |
| BaselineHead | baseline_id, project_id, kind, head_revision_id, lock_version | 只通过批准命令和 CAS 更新 head，业务引用 pin revision 不 pin 可变 head |
| ProjectionGeneration | generation_id, manifest_id, provider/build/schema/model_version, dimensions?, status, checkpoint, counts, digest | 图/向量/摘要均可删除重建；截断/解析不全不能报告 complete |
| ContextPack / Derivation | context_id, schema_version, image_revision_id, purpose, input_hash, artifact_ref, dependency_refs, policy_version, status | 内容不可变；stale 状态另记，不重写历史包；消费者能追溯输入集合 |
| BuildRun / WorkItem | build_run_id, goal_id, plan_revision, input_manifest_id, status, attempt, lease_epoch, output_refs, usage | 复用 AgentGoal/Step 基础，新增画像工件字段，不重复建第二套生命周期权威 |

建议实现为独立 PG 表并关联现有基线、对象、审批和工具记录。可变大小 payload 放 MinIO，PG 存类型化摘要、索引字段及 hash；不得把全部实体/版本藏进 settings 或单一 JSON。JSONB 仅用于有 schema/version 的扩展属性。

建议约束：`unique(binding_id, external_revision, manifest_hash)`；`unique(entity_id, revision_fingerprint)`；`unique(project_id, invocation_id, work_item_key, input_hash)`；同一断言去重键含端点修订/关系类型/方法版本。边的 project_id 必须与端点一致；审批者权限以提交时为准，不只看创建计划时。

Assertion 内容、EntityRevision payload 和 LinkDecision 均追加式保存；status 可以是派生读模型，但每个已冻结 ImageRevision 必须 pin 具体 assertion revision 与 decision ID。之后的纠正/否定产生新决定和新画像候选，不让历史快照因关联到“最新审核状态”而变化。ACL 撤销仍在读取时即时生效，与历史知识版本不可变是不同约束。

读取的复用边界同时包含操作生命周期、线程和 asyncio task。`ContextVar` 的复制不传递
数据库连接或已校验证据缓存的使用权：子任务、`asyncio.to_thread` 与延迟执行必须建立
自己的读取作用域并重新核验原输入；已结束的作用域不可使 SQLAlchemy Session 重新打开。
同一有效操作内可以复用固定画像、完整 provenance 和已校验 manifest，但不能复用来源
权限、当前 authority/review/publication head、执行许可或 worker lease。取消子任务只关闭
自己的资源；已有实时 S3 transport 的关闭约束仍有效，不能借旧缓存绕过归档缺失或损坏。

原料先上传私有 bucket 并校验 hash，再提交 PG 工件和 Outbox 同事务；未被提交引用的临时对象进入延迟 GC。S3/PG 不假定分布式事务。GC 不删除被历史 revision、审计保留或运行引用的对象；备份/恢复同时覆盖数据库和对象版本清单。

## 3. 身份、关系与证据

### 3.1 把外部代码图连接到需求和测试

```text
provider symbol@provider_index
  -> adapter normalization + source snapshot validation
  -> Nasus EntityIdentity + EntityRevision
  -> typed candidate Assertion with Evidence
  -> LinkDecision / deterministic evidence verification
  -> ImageRevision membership

AC@D1 <-implements- CodeSymbol@C1 <-exercises- Script@TestRevision
  ^                                                  |
  | asserts                                          | executed_as
TestCase@T1 ---------------------------------------> Run@Build
```

不把需求和测试硬写进 provider 私有图。provider 负责解析 code -> code；Nasus 在自己的证据图中连接 code -> AC -> case -> script -> run。Agent 只使用 Nasus ID；供应商节点键保存在 infrastructure 的 `ProviderBinding(index_generation, provider_node_id, entity_revision_id)` 映射中，失去映射可从快照重建。

0069 已将新物化的已登记代码对象切为 `CODE-<entity_id>`，并为已有 Provider mapping 审计回填不可变历史别名。新增固定画像身份查询与 canonical 回执，代码证据及受限来源投影兼容新旧 ID；不改写旧画像或授予语义/业务 authority。详见[稳定代码身份契约](./code-object-identities.md)。该增量不是完整 source registry cutover 或 rename/move/split/merge lineage 验收。

身份解析顺序：同 binding + 规范化符号签名/作用域精确匹配；Git rename + 内容/AST 指纹候选；最后显式 ambiguous。跨文件移动允许保留 entity_id，split/merge 产生新 ID 并记录 lineage，不能把两个旧符号都映到一个 ID。重载包含语言/包/作用域/签名；行号移动只更新 locator。没有稳定符号时使用文件身份+结构指纹+碰撞序号，并降低稳定性声明。

provider 替换先在同一不可变快照重新映射，未能唯一匹配的保持未解析且阻断相关自动晋级；不能通过“对 provider_node_id 做 hash”声称防腐完成。SCIP 可作为另一种符号定位输入，但其符号字符串同样不是 Nasus 主键。

### 3.2 关系语义

| 关系 | 来源 -> 目标 | 能证明什么 / 不能证明什么 |
| --- | --- | --- |
| contains / calls / depends_on / exposes | 代码结构 -> 代码结构/端点 | 某语言和解析策略下的观察；动态调用未解析需标明 |
| source_contains | requirement source revision -> AC/rule source revision | 原文字段的结构归属与固定父修订；不授予规范批准或测试覆盖。0046 的实际契约见[来源子对象](./requirement-components.md) |
| implements | code revision -> AC/behavior revision | 与期望有关的实现证据，不等于实现正确 |
| asserts | test case revision -> AC revision | 用例存在针对预期的可检查 oracle，不是仅提及需求 |
| exercises | script revision -> code/API/page revision | 脚本访问目标，不自动推出业务覆盖 |
| automated_by | case revision -> script revision | 脚本实现指定用例步骤和断言，需生成/审阅证据 |
| observed_in / executed_as | assertion/script -> run evidence | 对固定 build/environment 的一次观察，不自动普遍化 |
| contradicts / supersedes / derived_from | assertion/revision -> assertion/revision | 保留冲突、替代和推导来源，不是通过覆盖值抹去历史 |

兼容层对旧 `covers/validates` 返回摘要，不新增混淆的正式语义；旧边没有 oracle/定位则迁移为 `legacy_candidate`，不能补造 accepted。语言无关的端点/行为键用于跨语言连接，但同名方法绝不自动视为同一行为。

### 3.3 关联流水线与置信度

1. 提取 AC、业务规则、测试步骤/断言，保持 section/page/cell/行范围；中文分词、英文符号拆分和项目术语别名分别处理。
2. 显式 ID、接口 method+path+版本、测试元数据、构建/覆盖映射先产生确定性候选。仅“引用了 US-17”证明 references，不直接证明 asserts/implements。
3. 字面+向量+结构召回候选；每侧默认最多 30 个、扩大上限 100，记录候选截断。embedding 用语义召回，不能裁决真实关联。
4. 模型对候选输出 typed relation、双方证据 locator、reason_summary、反证和 unknown；JSON schema、端点类型、原文片段 hash 由规则校验。
5. 按证据裁决：可验证解析边标 observed；跨源语义边默认 proposed；规则满足经校准阈值且无冲突时可自动 accepted；关键 AC/业务规则变更需要授权 reviewer。
6. 回流用户确认/否定。人工 accepted 边端点改变后保留原修订决策，对新修订生成 stale/candidate，不把旧 approval 转移过去。

`confidence` 不复用 provider 固定分数。保存 evidence_strength、localization_quality、version_compatibility、ambiguity、method_version 和可选 calibrated_probability；未校准时概率为 null。初期跨源模型判断全进候选审阅。自动接受阈值只可在独立标注集达到精度门禁后按关系类型发布，召回不足优先保留 gap，不压低门槛补全图。

### 3.4 防止循环自证

每条 expected assertion 标记 authority_ref；模型根据代码生成的规则不具独立 oracle。测试代码的生成依据及验证来源必须可区分；两个 Agent 相互同意不算独立证据。新测试生成会增加“计划覆盖”，只有真实运行且断言通过才增加“已验证覆盖”。失败数据只能推导缺陷/环境/flaky 候选，不修改批准规范。

## 4. 版本解析与一致性

### 4.1 Snapshot 与 overlay

`resolve(image_revision_id, entity_id)` 的顺序是当前已准入 overlay、固定 parent revision；每条 operation 支持 upsert/tombstone。tombstone 命中立即返回 deleted，禁止 parent fallback 复活。关系也需独立 tombstone；任一端点在该 snapshot 被删除/不可见，该边不得用于遍历。

personal draft、version candidate、version shared、official 是不同可见集合。候选包只能供 authorized preview；正式质量任务默认只消费 approved 断言，显式允许的候选需带不确定性且不能满足强制 oracle 门禁。不能因为查询了 overlay 就把所有未批准知识当正式共享事实。

时间分两类：`recorded_at` 表示 Nasus 何时知道，`valid_from/to` 表示规范/观察声称适用的业务时间（可为空）。主要版本选择使用 manifest/祖先关系；迟到 run/doc 按它的目标 build/revision 挂载，不按到达时间挂到最新版本。历史审计支持“当时所知”与“现在回看那个版本”两个查询模式，不覆盖原审计。

### 4.2 更新与失效算法

2026-10-07 已落地同 binding、固定双 SourceRevision 的[文件差异查询](./source-deltas.md)，包括采集 inventory 缺口、完整计数/分页、未继承身份的 rename 候选和 canonical 无正文回执。它不执行下述 delta DAG、依赖失效或发布；`impact_complete=false`，完整 P4 仍待交付。

同日新增[固定上下文变更影响预览](./context-change-impact.md)：通过 quality_loop application port 验证已有 context/scope/generation/case/coverage/mapping 的完整有界依赖图；来源变化保守影响整个查询范围，包含新增节点和 negative/top-k 依赖。canonical 回执固定当时 inventory，历史展开不发现未来工件。它不写 stale、不改变批准或覆盖，仍返回 `impact_complete=false / invalidation_applied=false`；128 节点及性能限制、全项目派生索引与下面的正式失效算法继续待交付。

0067 在此预览之后增加独立确认的[持久上下文失效](./context-invalidation.md)：PG 追加式主记录及完整有界节点/边、审计/Outbox 原子提交；按精确 image revision 阻断当前使用，重新归档同画像的新 Context ID 不能绕过，其他画像不继承。下游通过 ContextPack port 接收 stale，不跨域改写原工件或批准。该命令 `invalidation_applied=true / impact_complete=false`，不等于全项目 Derivation 索引、增量编译、overlay 或下述完整算法完成。

新增[来源修订上下文反查](./source-context-roots.md)从项目内固定 source/image/context FK 发现多个画像的历史根，包含无召回命中的上下文。SQL 计数前过滤完整来源成员的当前访问权；canonical 回执固定原页、总数和权限 fingerprint，旧回放不发现未来根，权限变化连空页计数也拒绝。逐根图验证与失效仍是独立操作，该入口不授予执行权限或声明 impact_complete；全项目 Derivation/query-scope 索引和原子增量链继续待交付。

0068 新增[派生登记与冻结查询范围](./derivation-registry.md)，随 context/scope/generation/case/coverage/mapping 事实在原 Outbox 事务内登记全部直接依赖，迁移回填已有记录。来源根和质量 inventory 开始消费该索引，缺项拒绝返回完整结果；仍未包含全部实体／断言／authority／脚本／RunPlan 依赖，不把索引底座声明为完整项目 delta DAG 或自动增量链。

0070 增加[画像对象来源子图](./object-provenance.md)，同事务登记并回填固定 source、manifest、code、document、evidence、member 和 image_objects 根，正常读取及重复冻结均核验。编译局部的只读 PG 快照复用固定元数据，不缓存实时权限或批准头；完整统一派生图及自动增量链仍待交付。

0071 的[上下文来源锚点](./context-provenance.md)固定两个既有子图的 registration/root hash 与完整来源范围，随原 context 事务登记并回填历史，正常 ContextPack 消费核对连接。它不改变旧摘要或业务权威，不取代原文/ACL/批准检查；后续关系和规范连接使用独立新表，检索和执行依赖尚未完整登记。

0072 新增[冻结关联来源追溯](./relation-provenance.md)，在画像冻结和上下文归档事务内登记选定 references／implements／asserts 的双方成员、精确证据、原评估及完整审阅前驱，拒绝和暂缓也保持固定依赖。它不追随最新审阅头、不改变旧摘要或批准；未冻结关联、authority、publication、检索和执行依赖以及完整项目 delta DAG 继续待交付。

0073 将同一 v1 关系登记接入尚未被画像选定的已提交候选、评估与审阅：完整回填已有事实，正常读取、候选复用和命令恢复校验索引，新增决定先核验前驱，不能借新写入修复坏历史。复用判据来自持久候选及命令关联，不依赖旧 SSE 事件仍被保留；事件清理后整块登记丢失也拒绝，失败不提交新关联或事实事件。没有结果的预留不冒充完成，不修改 0072 根或 ContextPack 摘要。authority／publication／检索／执行依赖、自动项目 delta 和完整 P4 仍待交付。

0074 增加[规范批准来源追溯](./authority-provenance.md)，在原 AC／规则事实事务连接固定画像／成员／文档节点摘要与完整批准、撤回前驱；新当前修订首次登记，旧前驱及事件重放只读核验。规范读取和上下文 authority port 开始核验该连接，不复制 oracle 或改变原批准状态。

0075 的[上下文规范依赖登记](./context-authority-dependencies.md)将具体原始 AC／规则 pins 连接到规范修订及画像成员 registration hash，新归档同事务登记，包含未批准的负向依赖。历史迁移只登记精确待处理元数据，必须由当前 reviewer 独立确认、回读并验证原 archive 后补登记；不能用 PG 数量／当前批准头替代。正常读和事件核验缺项只拒绝、不修复，原 hash／oracle 不变。publication、检索、执行依赖及完整自动 delta 继续待交付。

历史待处理包现可通过知识页独立队列和 canonical `query.system_image.context.authority_backfill` 发现。查询只提供有界元数据回执，Agent 使用时重新授权并回读完整页；每个包仍需要另一条独立确认的登记命令。队列默认收起，错误时隐藏旧选择，不自动修复或清除 stale。此维护入口不是生成许可或完整自动 delta 完成证明。

0078 的[固定检索来源依赖](./retrieval-provenance.md)将原生索引预留、完整 generation/文档、trace 与 v5 ContextPack 连接到确切 publication 和成员 registration hash；两条原 trace 写路径及 context 原事务均登记，读取/恢复/事件只校验。v1-v4 保持无检索绑定的原契约。统一 query-plan/call/batch/模型调用、脚本/RunPlan 依赖、完整原子项目 delta、自动维护和五用途切换仍待交付，不修改下列目标算法。

1. 在固定旧 manifest 与新 manifest 上计算 add/modify/delete/rename，先计算全量 inventory，缺失目录/权限错误不能误判删除。
2. 为变更实体产生新修订，重建出入边；保留来源不变的人工决策引用。
3. 通过 Derivation 反向依赖闭包找到 assertion、摘要、context、case、script、run-plan；记录 stale reason 和 affected scope。跨域只发事件，不在画像域直接改用例仓库。
4. 查询依赖不仅记录召回到的实体，还记录 `query_scope_fingerprint`。新增节点可能改变原本无结果的查询；范围 fingerprint 变化也使旧 context stale。
5. 更新投影并校验计数/定位/源 hash。达到范围阈值（默认 >20% 文件变更）或解析器版本变更、图截断、依赖缺失时升级为全范围校验；未能界定影响时保守扩大回归，不静默漏测。
6. staging 工件验证后原子发布 candidate 指针，旧 approved snapshot 一直可用。失败工件不混入现有基线。

依赖遍历有 visited set、节点/边上限和超时；命中上限明确 `impact_incomplete`，关键用途阻断或扩为全回归。不能只截取前 N 条边还宣称完整。

### 4.3 多版本与发布竞争

fork 绑定 parent ImageRevision，不绑定 Official 的动态 head。A/B 并行版本分别拥有独立 manifest；release branch/hotfix 不按时间排序混合。merge preview 使用 base/ours/theirs，冲突类型包含规范矛盾、删除后引用、不同证据、权限变化、source 不同祖先。

审批 payload 固定 candidate_digest、manifest_hash、expected_head、rule_set_version 和 reviewer_scope。正式 publish 在同 PG 事务检查版本/授权/证据/审批并 CAS head，写审计+Outbox；任一不匹配返回 `409 stale_candidate`，不得重试为无条件覆盖。

跨多仓库发布 pin 每个 repo commit + 实际部署构建清单；存在不兼容组合时保留跨服务契约 gap。供应商只支持单工作树索引时按 manifest 隔离索引缓存，禁止多版本共享会变的 provider head。

### 4.4 权限撤销和数据保留

检索先做 binding/entity ACL + revision membership 过滤，再向量/图检索，再重排；禁止把无权内容先发给 LLM 再删答案。跨 restricted 边只返回不可用占位且不泄漏标题/数量。凭据引用、日志、对象 URL 均脱敏；对象下载走短期授权或 API 代理。

权限撤销后旧 context 不因“不可变”而继续可读；缓存 key 带 ACL epoch，读取和执行再次授权。保留/删除政策与法律要求冲突由管理员处理，删除使证据显示 revoked/redacted，不伪造历史完整。模型出网受项目策略，文档提示词和仓库指令视为不可信数据，不可修改权限、系统 prompt 或工具白名单。

原始命令回执的权限预过滤与最终校验必须区分“明确拒绝”和“无法核验”。工具列表、审计和
Agent 解释不能把服务故障、完整性错误或读取冲突转换成成功的空列表／部分历史。
平台列表只隐藏明确的 403 记录，其余原错误继续传播；画像资源预过滤器对损坏的已完成
合同返回脱敏的 502，对不可用的授权服务返回脱敏的 503。未建立有效资源范围的失败／待确认
尝试不冒充已完成工件；明确撤权仍不可见。成功结果仍复核当前来源 cohort，任何异常路径
都不执行工具、补造事实或修复历史；恢复读取必须使用原记录及原摘要。

## 5. 用途上下文包

0101 新增[执行计划准备](./run-plan-preparation.md)，完整保留原 context/scope/generation/mapping、用例/步骤/oracle、脚本和独立审阅，并以精确 FK/hash 连接 0100 登记。保存必须通过当前 reviewer 的新鲜 canonical 确认，历史读取先核验来源授权和原输入，不追随最新工作区。build/environment/fixture 仍仅为声明，prepared 不代表已核验目标或执行权；实际构建、独立执行授权、canonical 运行、真实覆盖/放行、旧链及五用途切换继续待交付。

0100 增加[脚本与审阅派生追溯](./automation-provenance.md)：脚本固定原 context/scope/generation/coverage/mapping 和全部选中 case 的工件/登记摘要，审阅固定原脚本与确切前驱；事实、登记、审计和 Outbox 同事务。正常读、已有命令恢复和事件只核验，缺失历史拒绝，迁移单独显式回填。它不修改旧 v1 图和摘要，也不扩展公开 impact/invalidation 至完整项目 DAG；RunPlan/真实目标覆盖、自动 delta 和下表五用途保持原交付范围。

0098/0099 新增[固定用例脚本草稿与独立审阅](./automation-script-drafts.md)：完整原 context/scope/generation/mapping 和 case/step/oracle 进入精确预算确认、PG 持久预留、原生回复/usage 与私有 MinIO 草稿。独立审阅保存每个 DSL 动作及原断言的追加式决定，前驱 CAS、角色/来源复核和审计/Outbox 同事务；原脚本保持 draft，接受仍为零自动化/执行/通过。Agent 回执重新核验，不存在直接 HTTP 导入/批准入口。Portal 已接入折叠预算、原命令分页发现、失联只读恢复、逐动作/oracle 审阅及上游事件刷新；交互协议与原生 API 验证范围分开记录。当前只支持一次完整有界模型调用，公开恢复/Temporal/取消/fencing、完整移动可用性、automation ContextPack、目标 build/environment/fixture RunPlan 与下表五用途仍需交付。

2026-10-10 新增[固定审阅用例的自动化输入衔接](./automation-input-preview.md)：通过 application ports 回读原 context/scope/generation 和当前独立映射，保留每个步骤、oracle 及全部强制义务，不读取旧可变工作区。HTTP/Portal 为只读检查，返回五项阻断与零自动化/执行/通过，不授予模型或 Runner 权限；新失效/映射事件重新核验。实际 exweb 来源成员及全部归档文件验证与浏览器 transport fixtures 分开记录。完整 automation ContextPack、预算化脚本生成/独立审阅、RunPlan/真实目标执行和下表五用途仍需交付，旧质量消费者尚未全部切换。

### 5.1 公共 envelope

2026-10-10 的 [Runner 执行观察](./runner-execution-observations.md)将实际 wire request、逐步骤/断言结果及请求摘要连接到 Run 私有归档，并保留派发时的兼容 TaskContext ID。Run 与完整 evidence 元数据在同一 PG 事务保存，兼容投影在成功后更新；同提交入口完全相同结果可重放，改变原事实拒绝。该增量不绑定完整 ContextPack、case/oracle、脚本修订或 target build，`case_ref=None`、business/build verified=false；MinIO/PG orphan GC、canonical 审计/Outbox/终态原子链、完整 RunPlan 和真实覆盖仍需交付，不能把步骤通过等同业务验证。

```json
{
  "schema_version": "nasus.context-pack.v1",
  "context_id": "ctx_example",
  "project_id": "project_example",
  "purpose": "test_design",
  "image_revision_id": "image_example_2",
  "source_manifest_id": "manifest_example_2",
  "target_refs": ["ac:refund-window@2"],
  "policy_version": "quality-policy@1",
  "facts": [],
  "required_constraints": [],
  "evidence_catalog": [],
  "conflicts": [],
  "gaps": [],
  "dependency_refs": [],
  "query_scope_fingerprint": "sha256:example",
  "readiness": {"status": "blocked", "reason_codes": ["missing_oracle"]},
  "retrieval": {"generation_ids": [], "fallback_used": false, "truncated": false},
  "budget": {"max_tokens": 12000, "used_tokens": 0},
  "content_hash": "sha256:example"
}
```

示例是结构示意，不是已就绪上下文；Evidence 对象具体为 source_revision + locator + content_hash + access_scope。每条 fact/constraint 引用 evidence ID、语义类别、批准/候选状态和适用版本。`content_hash` 由 canonical JSON（排除自身 hash、交付时临时 URL）计算；包括目的、来源修订、策略、必选事实和模型配置版本。

### 5.2 用途 payload 与后置条件

| Purpose | 必选 payload | 后置校验 |
| --- | --- | --- |
| us_design | capability/actor glossary、现状 observed 与期望 expected、流程状态、兼容约束、相似 US、影响范围、未定决策 | 每条 AC 有 authority 或 pending_confirmation；不得把假设写成现有批准需求 |
| test_design | AC revision 集合、observable oracle、风险边界、权限矩阵、状态转换、历史不变量、复用用例、正反例 | 每个强制 AC/风险映射到 testcase 或显式 gap；case 记录 preconditions/input/steps/expected/source |
| automation | approved case revision、framework/toolchain、API/DOM locator 证据、fixture/schema、setup/cleanup、wait/time-control、secret refs、允许网络目标 | 脚本 AST/编译/collect 校验、断言与 oracle 对齐、禁用任意 shell/生产域名、不硬编码密钥 |
| execution | script/content digest、build/commit manifest、environment/version、dependency contracts、fixture isolation、mandatory regression、approval、budgets/retry | preflight 重新核对部署身份和授权，执行不可漂移到最新脚本；run 收集每断言状态/截图/日志/trace |
| release | AC denominator snapshot、强制回归项、run evidence、failure/flake/waiver、freshness/compatibility、risk gaps | 缺失/过期/未运行不能算 pass；拒绝用历史 build 的成功填充当前证据 |

`RegressionProfile` 的选择依据是 changed behavior + graph impact + mandatory tests + historical incident protections 的并集，再按风险安排顺序，不用 top-k 排名删去 mandatory 项。环境执行成本超预算时返回计划未覆盖部分和 release blocker，不偷偷缩小回归范围。

`CoverageMatrix` 每行是 AC revision / risk invariant，每列区分 planned case、assertion-mapped、automated、executed_on_target、passed、unknown；分母来自 pin 的批准 AC/规则清单，分子不能靠生成更多重复 case 增长。代码覆盖率是另一维度，不能等价业务覆盖率。

### 5.3 编译过程

1. 确定 project、purpose、目标 image revision 和 target refs，校验权限。
2. 载入强制规则、关键 AC、历史不变量、冲突和目标环境约束，先预算保留。
3. 对可见且匹配 revision 的代码/需求/测试混合召回，按 typed graph 扩展上下游，负向决策过滤候选，重排取支持证据。
4. 去重并压缩解释性摘要，保留 evidence handle 以按需展开。摘要不得取代原文 oracle。
5. 校验来源、版本闭包、强制项、ACL、缺口和 token 预算，持久化 ContextPack + Derivation + RetrievalRun。
6. 下游执行前以 target/ACL epoch/policy/digest 再校验。过期返回可操作错误，不静默用当前最新版替换。

默认 12k input token 可配置；强制项超限先拆按 AC/模块的多个子包，每子包继承全局安全约束，禁止裁掉强制项。不能拆分的任务暂停请求更大预算。rerank 失败走记录过的字面/结构 fusion；embedding 不可用只出可定位词法结果并标 partial，hash vector 不具语义召回能力，生产不得据此声明语义检索 ready。

## 6. 防腐端口与部署

以下是新增/扩展的 application 端口，参数和返回值均为 Nasus DTO：

| 端口 | 操作 | 契约 |
| --- | --- | --- |
| SourceSnapshotPort | probe, capture, diff | 固定 revision、inventory、排除范围；不能执行仓库任意脚本 |
| CodeIntelligencePort v2 | capabilities, prepare_index, status, entities, relations, locate, impact, cancel | snapshot/index handle、游标、supports/degraded、exact/approximate locator、截断与完整性 |
| DocumentUnderstandingPort | parse | 章节/页/单元格/表格+原文定位，不能只有一段摘要 |
| TestAssetUnderstandingPort | extract_cases, inspect_scripts, import_run_evidence | 静态抽取和已授权执行分离；记录 framework/fixture/oracle |
| SemanticAnalysisPort | propose_behaviors, propose_links, detect_conflicts | 结构化候选、模型调用审计、预算；不准直接落 accepted |
| ContextQueryPort | compile, expand_evidence, compare, explain_gap | 目的、版本、ACL、token_budget 必填，供应商不泄漏到上层 |
| ImagePublicationPort | preview_merge, validate, publish | 治理/审批/expected_head；实现只由 ToolRuntime 调用 |

供应商不支持 diff/impact 时 Nasus 可用快照 diff + 已准入边计算保守范围，不能伪装供应商执行过。provider-neutral schema 保留原始关系种类和可靠性元数据，不能把所有边压成 depends_on 后丢失语义。

2026-10-07 已增加[代码图执行控制与完整性边界](./code-graph-execution-control.md)：原业务权威的运行期复核、受控进程组、只含批准原文的临时快照/私有索引、公开关系查询分区及明确截断；合成路由、模糊调用和错误 Java import 保持 gap。该增量不把原 `analyze` 包装成已完成的 Provider v2，也不把同账号缓存或探针通过声明为独立账号/禁网/资源隔离、能力协商或完整 gold。

后续类型化能力声明和 `nasus.code-analysis.v2` 分析报告已贯通适配器、PG 查询与 Portal：保留每个 Provider 的实际操作、已声明/未知语言、限制、读取/定位状态及具体 gap；旧报告不回填。声明是本地契约，不是原生功能协商，分析记录 ID 也不是可恢复的原生 index handle。

2026-10-08 的[代码观察归档](./code-observation-archives.md)进一步将完整 received 投影及原生查询解码响应固定到私有 MinIO，`nasus.code-analysis.v3` 的追加式报告保存摘要和 source/hash pin。未解析实体和转换前原生关系保留为观察，不进入正式身份或覆盖；公开分页只返回去除私有引用的规范观察。实际查询范围和完整原生数据库导出仍严格区分，旧报告不虚构历史正文。

同日 `PreparedCodeIndexPort` 增加真实 Worker 会话的 prepare/status、规范化候选分页、定位、保守静态影响与独立取消信号，并接入原分析链。原生索引在多次读取间实际保留，游标绑定确切会话/集合，最后清理；`worker_owned_session` 不承诺 PG 持久 handle 或跨重启恢复，candidate IDs 不替代 Nasus 实体 ID，静态影响始终 incomplete。详见[执行边界](./code-graph-execution-control.md)。上表完整持久生命周期、原生能力协商、跨 Worker 取消和完整影响/性能验收继续待交付。

0079 后续增加 PG 固定 generation、append-only 首次投影摘要/Worker attempts 与独立 epoch 租约，确认式结构构建已实际消费。内部 `reopen` 从确切归档快照重建原生索引，拒绝 Provider/input/输出漂移及旧游标；跨进程协议恢复和固定 exweb 原生重建已有专项证据。该持久 generation 不替代 Nasus 实体身份或 ToolInvocation，旧无 callback 的 materialize 入口仍未切换；自动 Workflow 恢复、强杀清扫、公开生命周期、跨主机/隔离/性能/原生协商及本表完整 v2 契约继续待交付。

0080 已在持久 prepare 中增加实际 MCP initialize/tools-list 契约协商及追加式 PG receipt。探测用空私有 HOME/cwd/PATH，不传批准源码或应用凭据；只验证消费的输入 schema，不调用供应商工具。CLI 0.8.1 与 serverInfo 0.10.0 分开保存并标 mismatch，namespace/query-format 未广告字段保留 gaps；工具清单不等于语言、定位或关系 completeness。重建时 receipt 必须完全一致，历史缺失/损坏拒绝，不伪造回填。0081 进一步约束同 invocation/binding 只登记一个 generation，普通 `open_index` 重试不能换 Provider 或源版本绕过原 pin；历史冲突拒绝升级且不改写事实。详见[原生契约与命令固定](./code-graph-execution-control.md)。完整业务 Workflow、公开生命周期、隔离/清扫/性能、CodeGraph/gold 及本表完整 v2 仍待交付。

代码索引运行在受限 Worker/子进程，独立服务账号及缓存、最小环境变量、禁网（显式模型出口例外）、CPU/内存/文件/输出大小/超时上限；默认仅静态解析。服务端不用供应商全局 install/自动更新/修改 IDE 配置功能。只挂载本次批准 scope 的临时快照，不能指向开发者主目录。

CBM 当前文档描述账户级协调/缓存约束，因此不能假设换 CBM_CACHE_DIR 就实现并行租户隔离；采用受隔离服务账号/容器的 worker pool，同实例同版本，必要时串行，具体通过 P0 两项目测试确认。供应商内部 SQLite 是可丢弃私有索引，不是 Nasus 后端业务数据库；若组织禁用任何 SQLite 文件，需选择其他 adapter，不偷换 PG-only 业务事实约定。

保留现有 host API/Portal/Runner/Workflow + Docker PG/MinIO/Temporal 的开发约定。可选 Docling 等独立解析 worker 用自身兼容 Python 环境，不强制 API 同轮升级。发布候选锁 release SHA、artifact checksum、schema、许可证/第三方模型清单；禁止 `latest` 自动更新。

## 7. 命令、查询与事件

保留当前正式 Tool ID：`system_image.sources.register`、`system_image.sources.ingest`、`system_image.context.materialize`、`system_image.baseline.initialize`、`query.system_image.status`、`baseline.promote`。新增参数均通过版本化 schema 兼容；旧无 revision 调用在命令接受时解析并 pin，后续不随 head 漂移。

当前已新增只读 `query.system_image.evidence.list/read`，走同一 ToolInvocationRuntime、项目 RBAC 与审计。list 必须给出 source revision + object ID，支持 entity revision pin；read 必须给出 source revision + evidence ID，返回有界页的读取 receipt。receipt 是调用时的校验证据，不是永久访问授权或正文缓存。`ToolEvidenceObservationApplicationService` 提供重新授权的 metadata describe 与归档正文 expand；Agent 重规划已接入 describe，HTTP 可经 `/v1/tool-invocations/{id}/evidence` 使用 expand。原文在内存中按需展开，不写入调用结果/SSE，不自动发给模型；来源级 ACL/模型出口及完整自主调查仍未完成。

拟新增能力（proposed，不声称已在 catalog）：

| Tool | 权限/作用 |
| --- | --- |
| system_image.build.plan / system_image.build.start | 规划/启动或恢复已批准 BuildIntent，start 带 plan digest、预算确认 |
| system_image.build.replan / system_image.build.cancel | 同一 goal 更新计划/取消；不能绕过新增 scope 的 gate |
| system_image.sources.refresh | 指定 bindings/ref 的新快照，触发增量计划 |
| system_image.links.review | 授权 reviewer 接受/否定指定候选断言修订 |
| query.system_image.context / query.system_image.diff | 版本化上下文包或差异的可审计查询 |

建议 HTTP 薄层：`POST /v1/projects/{project_id}/system-image/builds` 返回 202 + build_run_id/goal_id/events_url；`GET .../builds/{id}` 快照；`POST .../builds/{id}/resume|cancel`；`GET .../revisions/{id}`；`GET .../diff?base=...&target=...`。不新增绕开工具授权的写入口；router 调用 ToolRuntime application facade。草案发布沿用 baseline 工具链，不再建另一个旁路 publish 接口。

写请求要求 Idempotency-Key（project+actor+operation 范围），同 key 同 fingerprint 返回原 run，不同 fingerprint 返回 409。source manifest 不兼容/审批过期 409；缺字段或非法类型 422；权限不足 403；资源上限 429 或可恢复 paused；引用未知 ID 不泄漏跨项目存在性。

拟新增事件：`system_image.build.accepted`、`work_item.started/completed/failed`、`plan.revised`、`build.paused/cancelled`、`candidate.ready`、`revision.published`、`context.invalidated`。envelope 带 project/goal/run、revision、invocation、sequence、event_id、causation_id、correlation_id；状态工件与 Outbox 同 PG 事务。SSE at-least-once，以 event_id 幂等，Last-Event-ID 重放；权限变更时重连重新校验。查询快照才是事实，进度 token 不是持久化结果。

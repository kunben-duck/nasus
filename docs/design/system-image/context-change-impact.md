# 固定上下文的变更影响预览

状态：2026-10-07，P4 的上下文依赖追溯切片。该查询提供完整固定集合的只读预览，不执行持久失效、增量重建或发布；0067 已新增独立确认的[上下文失效命令](./context-invalidation.md)，不改变查询的只读语义。具体运行结果见[实施记录](./implementation-progress.md)，完整退出条件仍按[交付方案](./delivery-and-evaluation.md)。

## 输入和依赖范围

输入固定 `project_id / context_id / context_artifact_hash / before_revision_id / after_revision_id`。双来源修订必须属于同一个 binding；before 必须是该 ContextPack 所属冻结画像的 captured 来源。不能用当前 source head 或新的画像替换历史上下文。

不知道 ContextPack ID 时，先用[来源修订反查](./source-context-roots.md)发现项目内当前可读的归档根，再逐根调用本查询。反查和逐根图验证不是一次原子项目快照，不因此声明全项目影响完整。

依赖链为 ContextPack → ScopeRevision → GenerationResult → Case / Coverage；MappingRevision 依赖 GenerationResult，scope/mapping 的历史前驱同样纳入闭包。新增文件可能影响空查询和 top-k 选择，所以不能仅匹配已有 evidence 文件。当前策略在任一新增、修改、删除或 inventory 缺口时，保守标记整个固定上下文的派生集合需要重新调查；相同完整文件内容不产生 affected 集合。

`query_scope_fingerprint` 固定原上下文 input digest、画像工件 hash 和完整 source members。这是原查询范围的身份，不是新画像或已重新执行检索的结果。`graph_hash` 固定节点身份、工件 hash 和所有依赖边；case/coverage 从完整验证的生成结果和 PG 投影推导，不采信外部传入的 coverage 声明。

## 领域边界与完整读取

- system_image application 通过 quality_loop application read port 获取依赖，不直接连接或写质量域 repository。
- quality_loop 的单条 PG union 查询固定当前项目/context 的 scope、generation、mapping ID 集合，然后调用已有完整历史读取 use case。每份工件核验来源、hash、context/scope/oracle、前驱及即时权限，不只信 metadata 表。
- 领域验证唯一身份、完整祖先、允许的边类型、唯一 context 根及无环闭包。case/coverage 不允许跳过 generation，generation 不允许跳过 scope。
- 预览最多 128 个展开节点、64 KiB；PG inventory 最多 127 份质量工件，另外保留 context 根。超限返回 413，不截取前 N 项、不声称部分结果为完整闭包。该上限尚不能满足完整大规模 P4 容量要求。
- 来源读取、inventory、工件回读和返回边界重新检查原 ACL scope；撤权后不返回旧依赖集合或私有正文。完整性失败返回脱敏 502。

`dependency_closure_complete=true` 仅指本次固定的已有质量工件集合已完整展开和验证。它不包括全项目所有断言、索引、摘要、脚本、RunPlan 或未来新增工件。返回固定 `impact_complete=false / invalidation_applied=false / generation_authorized=false / execution_authorized=false`，不构成全项目业务影响证明或执行许可。

## 正式入口和历史回执

HTTP 入口：`GET /v1/projects/{project_id}/system-image/context-packs/{context_id}/change-impact`，查询参数为 context 工件 hash 和两个来源修订 ID；响应 `private, no-store`。没有旁路写 API。

canonical 工具 `query.system_image.context.change_impact` 复用 ToolInvocationRuntime 的项目权限、审计和 Outbox。ToolResult 只保存请求、固定依赖 IDs、hash、计数及明确的只读语义；不保存原文、路径、oracle、存储地址或来源字段。Agent 中英文查询使用既有 12 个详细工具预算，观察时重新授权和完整回读。

旧回执固定当时的 scope/generation/mapping inventory，展开时不重新发现后来记录；case/coverage 从固定 generation 重建。新查询可以发现新记录并形成新的 graph hash。回放逐项验证原工件及整个结果摘要；追加审阅不会改变旧图，但撤权和损坏仍使回放失败。新回执不是当前任务继续生成的授权。

## exweb 验证范围

新增专项以实际 Git 对象导出 `cd9195691f2205d671fe61ba14e47744b5187ad6` 和 `fe5827f6b76f77ef34918d8b452ee823142332dc`，不修改共享 clone、不运行 hooks/Maven 或目标程序。导出目录通过 canonical 本地来源登记、摄入和物化；来源外部修订为内容 hash，不冒称 Git connector 的 tracked_ref 验证。

来源、画像、上下文和质量工件使用隔离 PostgreSQL/私有 MinIO。伴随 Search 需求/历史用例、Orders sentinel、批准 oracle 和生成回复均明确为协议夹具，不是 exweb 维护者业务 gold 或外部模型输出。专项检查真实新增文档和 README 修改对固定查询范围及已有派生链的保守影响、canonical 回放及 Agent 重新授权；实际结果以实施记录为准。清理只覆盖本次记录的 MinIO keys，不覆盖其他验证报告或对象。

## 后续完整交付

本预览是持久 Derivation/invalidation 的前置，不替代它。0067 已交付固定画像当前使用的独立 stale 事实、完整有界节点/边、跨域事件及当前消费者门禁；全项目反向依赖索引与实体/断言 lineage、新 source/image 的增量编译、negative/query scope 更新、overlay/tombstone、merge/CAS/回滚及 webhook/reconciliation 仍需交付。五用途、旧生成链切换、脚本/RunPlan/真实执行反馈、容量与性能、P0-P6 和最终 V1 门禁全部保持原范围。

# 完整断言的分片审阅协议

更新：2026-10-03。已交付领域分片/校验/归并、重新授权的只读接口、0066 私有分片追加式保存、完整集合预览、canonical 最终提交及 v2 历史/回执实现。Portal v2 读取/撤回已有专项验证；分片编辑和最终确认已接入，浏览器操作验证状态见实施记录。不是端到端大规模批准或 P5 完成。原[映射契约](./test-design-mapping.md)和[完整交付门禁](./delivery-and-evaluation.md)保持不变。

## 分片与完整性

v3/v4 结果允许最多 32768 个案例，每案例最多 256 条断言。旧 v1 输入最多 8192 条；不通过裁剪案例/义务、把断言数当案例数或只提交前一页来适配。旧输入、工件和回执限额保持兼容。

`nasus.test-design-mapping-plan.v1` 固定项目、generation ID/hash、context/scope pins、input/proposal digest、审阅前驱和分片策略。案例及案例内义务按 ID 排序，每片最多 128 个 `(case_id, row_id, step_index, oracle_digest)`。片 digest 包含序号，按序摘要形成 layout digest；plan digest 包含完整绑定和全部数量，不依赖供应商节点 ID。

计划只返回总数和 layout digest，不返回所有分片目录。查询仍验证完整 proposal，只保留请求片的有界元数据；超既有生成契约限额则显式拒绝，不截断。这不是增量索引，完整查询性能和内存门禁仍须另测。

`verify_partition_decisions` 要求每片每对断言恰好一次、顺序不变、步骤/预期摘要不变，只允许 accept/reject/defer 和有界理由。额外批准/执行字段拒绝。

`assess_partitioned_mappings` 从完整固定 proposal 重推全部片，消费按序迭代器。缺片、重复、乱序、错误计划/片摘要、最后一片不完整均失败，不返回部分 assessment。复用原覆盖归约器，保留分母和 gap，automation/target execution/pass 仍为零。

领域函数不接触 ORM/模型/SSE，不创建批准事实。摘要不能替代 canonical 确认、认证 reviewer 或提交时来源权限。

## 只读接口

```text
GET /v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-plan?artifact_hash=...
GET /v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-parts/{sequence}?artifact_hash=...&plan_digest=...
```

仅当前 qa_lead/project_admin/platform_admin 可读；回读原 generation 的完整 provenance、原来源权限和映射 head，返回前重查 head 与原授权 scope。页请求必须匹配重推的 plan digest；前驱变化返回 409，越界页返回 400，非法序号返回 422。历史 scope 失效可以检查固定元数据，但不获得新审阅许可。

响应 `private, no-store`，断言仅含 ID/步骤索引/摘要，无原文 oracle、模型凭据或私有对象地址。`review_authorized=false`、`execution_authorized=false`；查询不创建分片、mapping、审计批准或模型调用。

## 私有分片暂存（0066）

`quality.test_design_mapping.stage_part` 是需用户独立确认的 canonical governance 工具。输入固定原 generation/hash、完整 plan digest、映射前驱、片 sequence/digest、该 reviewer 的片编辑前驱，以及全部有序 1..128 对决定。不得携带批准/执行字段，不能少交、多交、重排或修改 oracle。客户端 `confirmed_by_user` 不跳过确认；首次提交要求当前有效账号/项目 reviewer、精确命令/actor、15 分钟确认 TTL、当前完整来源权限和 scope。

`quality_test_design_mapping_part_revisions` 只存类型化绑定与有 hash 的摘要；正文保存在独立私有 `test-design-mapping-parts` MinIO namespace。项目、generation、plan、片序号、reviewer 和修订组成完整前驱 FK；首修订唯一、后续 CAS，数据库拒绝 update/delete 和有数据时 downgrade。预写对象和 PG 不构成分布式事务：提交锁内重新展开全部 generation provenance，重验来源/scope/映射 head/片 head，分片、审计、Outbox 同事务提交。失败可留下未引用工件；GC 仍属于未完成的 P6。

同 invocation 重新读取原私有工件、canonical provenance 和当前来源访问权后返回同一修订，不重写正文或新增事件。映射 head/scope 后来变更时仍可授权读取原暂存，但 `part_current=false`；此历史读取不重新激活它。不同 reviewer 拥有独立暂存链，qa_lead 不能读取另一个 reviewer 的私有决定；project_admin/platform_admin 可按自身来源权限检查，但不因此成为原决定的 signer。

```text
GET /v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-parts/{sequence}/staged?artifact_hash=...&plan_digest=...
GET /v1/projects/{project_id}/quality/test-design-mapping-parts/{part_revision_id}
```

头查询重新验证完整来源和当前计划，仅返回调用者自己的 metadata head 及最近五个摘要，显式给出总数和 `history_truncated`，不返回决定正文。固定修订读取重新校验原请求、完整计划/原断言、canonical actor 和工件摘要，响应 `private, no-store`，不暴露私有对象地址。恢复未知提交结果应先读头与固定修订，不自动重发新命令。暂存始终 `assertion_mapped=false`、`review_authorized=false`、`execution_authorized=false`；不会新增最终 mapping 或修改原 draft/CoverageMatrix。

## 完整集合的独立最终确认（v2）

`GET .../test-design-results/{generation_id}/mapping-finalization?artifact_hash=...&plan_digest=...` 只选择当前 reviewer 自己的各片 head，返回固定计划、已保存/应保存数量、全量有序成员摘要的集合承诺。未齐备时明确 `ready_for_confirmation=false`，不返回可批准的集合承诺；齐备时仍回读每个原私有工件并验证全部断言，不把 SQL metadata 当决定正文。预览无写入、模型出口或批准。

独立 canonical `quality.test_design_mapping.finalize` 输入仅含原 generation/hash、plan digest、完整 `part_set_digest`、映射前驱和理由。集合 digest 绑定 reviewer、全部片修订/工件/请求/原片 digest 和完整数量，不接受巨型 mappings/members 数组。15 分钟精确确认、当前账号/角色/来源/scope 与项目锁内所有 head 重验仍必需；预览后编辑任意片、缺片、乱序、不同 signer 或取消均不能换成另一集合批准。最终映射、审计和 Outbox 同 PG 事务，正文为独立 v2 私有工件，原 draft 不改写。

最终工件保留全部精确片引用，历史读取重推原 plan、全部决定和 assessment，不绑定后来片 head。v2 metadata 固定 schema/plan/set 摘要，另有 v2 receipt 容纳原完整断言数量；v1 输入及 receipt 的 8192 上限不扩大，v1 工件仍保持 8 MiB 限额。v2 工件有单独 512 MiB 上限，超过则拒绝，不裁剪；完整容量、内存、MinIO 和查询性能尚无通过证明。旧 `quality.test_design_mapping.review` 的 withdrawal 仍追加在同一映射历史，不改写 v2 原审阅。已提交命令即使终态 ack 丢失也只恢复原 fact，不重开原 failed 命令。

另一项目 reviewer 可按当前来源权限检查最终 assessment；内部验证只能通过持久化的 exact final authority 访问它绑定的原私有分片，不开放另一个 reviewer 的暂存正文。历史读取和最终确认均不增加 automated/executed/passed 或执行许可。

## Portal 操作与证明边界

用户显式打开“按分片审阅映射”后才读计划和当前片。前端从完整原草稿重推所有分片摘要和 Unicode code-point 顺序，不改旧 v1 的 8192 限额；超过 v1 限额的草稿只能走完整分片写入，不创建截断的 v1 意见。一次编辑最多 128 对断言，界面按八对分页和无可见滚动条的局部滚动展示；提交仍包含这一片的全部决定。

个人头/最近五个历史摘要和固定私有工件逐项核对 plan、来源、signer、顺序、步骤/oracle、原请求及正文 hash。刷新、重新读取或修改意见使保存确认失效；未知 ack 只读原头和历史，不自动创建新写命令。读失败隐藏父草稿，避免通过旧缓存继续查看受限内容。

完整集合预览不返回私有决定或所有成员，前端只校验常量大小的 commitment envelope；原私有工件和完整成员验证由后端执行。分片操作/导航使旧预览及确认失效，全部齐备后才出现单独的最终审阅说明和确认。最终写入仍经过 canonical ToolInvocation，而不是前端直接批准数据库事实。

已归档 v2 读取则返回所有有序五字段成员元数据，以供前端重推集合和整个最终工件 hash，不暴露私有理由。前端还按完整原义务重推全部 classification/assessment；旧 v1 和 v2 历史、同链 withdrawal 均保留严格校验。整个 v2 archive 读取仍非分页协议，完整容量与性能尚须验收。

## 剩余交付与验收

1. 实际 PG/canonical/MinIO 最终写链专项已终态通过，仍需完整组合权限/容量/性能和最终全量门禁；不以纯契约测试替代真实批准链。
2. Portal 单片编辑、精确版本保存、全部保存后独立最终确认的最终浏览器和组合回归；v2 历史读取/撤回已验证，但操作协议 fixture 不等于浏览器创建真实后端批准。
3. 完整大规模链路、主题/移动布局、查询与私有工件回放性能，以及固定 exweb 最终 v2 集合验证。65536 个成员的纯摘要测试只验证常量大小承诺和末片完整性，不是实际 PG/MinIO/多批容量证明。

以上均属于完整目标，不因只读 API 或领域容量测试通过而视为完成。

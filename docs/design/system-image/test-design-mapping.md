# 草稿用例的独立断言映射审阅

更新：2026-10-03。0061 新增后端、不可变记录和 Portal 审阅入口；验证记录见[实施进度](./implementation-progress.md)。这是完整 P5 的一部分，不代表自动化、目标执行、业务准确率或 V1 已验收。

## 领域边界

生成结果始终是固定输入下的 draft。其 planned CoverageMatrix 和 `mapping_approved=false` 保持原样，后续审阅另存，不通过修改旧草稿补造批准。映射接受只说明 reviewer 认为用例断言与指定测试义务的预期一致，不批准来源 AC/规则，不证明真实运行或通过。

`quality_loop` 拥有映射审阅，通过结果 application port 读取精确 generation；不直接访问画像、上下文或模型 repository。领域评估无 ORM、模型、存储和框架依赖。PG 保存审阅元数据与前驱，私有 MinIO 工件保存完整 request、generation pin 和派生 assessment。

每次审阅固定：project、generation ID/hash、原 context/scope pins、input digest、proposal hash、当前审阅前驱、策略、认证 reviewer 和 canonical invocation。每个 `(case_id, row_id)` 必须恰好出现一次，并保持 `step_index / oracle_digest` 不变；不能漏掉、重复或发明关联。

## 审阅及覆盖语义

- 每个断言关联选择 `accept / reject / defer`，必须给出非空理由。初次 UI 不预接受，全部为暂缓且理由为空。
- 每项义务至少有一个 accepted 断言，才计入 `assertion_mapped_count`；重复案例不能增加原约束或义务分母。
- 用例所有断言都接受，才进入 `accepted_case_ids`。全部义务有接受映射且没有显式 gap，才 `mapping_complete`。
- `automated / executed_on_target / passed` 均为 false、对应计数为 0、unknown 保留，`execution_authorized=false`。
- 改判追加新修订；withdrawal 只可撤回当前 reviewed head。原 scope 已失效时可撤回，但不能新审阅。
- 历史内容与 assessment 不改写；`current_use` 重新检查 scope 与审阅 head。历史不可变不能绕过即时来源 ACL。

## 正式入口与安全

只读 HTTP：

```text
GET /v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-review?artifact_hash=...
GET /v1/projects/{project_id}/quality/test-design-mapping-reviews/{revision_id}
GET /v1/projects/{project_id}/quality/test-design-review-drafts?after_id=&limit=3
```

上述接口均 private/no-store，校验当前账号、项目和全部来源访问权、固定结果、工件 hash、canonical provenance 和派生覆盖。无结果 JSON 导入接口。

项目级发现接口要求当前 qa_lead/project_admin/platform_admin，只返回 metadata、context/scope pins，不返回正文、私有地址、凭据或管理员 job。使用 generation ID keyset 分页，默认 3、最大 5；游标、每项及 look-ahead 均重新授权并完整回读验证，结束时再次检查角色/ACL。任一记录无权或损坏则整页拒绝，不返回部分 ID、游标或 total。历史 scope 失效不删除旧草稿，但不授予当前生成/执行权限。分页不是固定目录快照，新增记录可能落在游标之前，需显式刷新；完整归档回读有界但性能门禁仍未证明。

`query.quality.test_design_review_drafts` 将独立发现接入 canonical ToolRuntime。请求固定 project、after_id 和 limit；结果只含严格有界且有序的 generation IDs、完整 metadata 页 digest 和下一游标，不缓存源码/用例正文、模型配置或生成任务。query 本身仍要求当前 reviewer 角色，不因低风险只读而放行 viewer/tester。Agent 观察旧回执时重新读取完整页并检查来源 ACL、角色、归档及 context/scope pins；页面变化即失效，不能作为生成或执行许可。分页不是固定目录快照。

`query.quality.test_design_mapping` 返回 ID/hash/状态/计数等无正文回执，Agent 再次使用时重新核验。正式写入只能通过 `quality.test_design_mapping.review` + ToolRuntime `user_confirm`；需要 qa_lead/project_admin/platform_admin，15 分钟且非未来的精确确认。不能继承别人的会话/goal 或把请求里的 confirmed 字段当授权。

项目与 ACL 锁内复核账号/角色、generation/scope/原文权限及审阅前驱；CAS 失败要求人工重新读取、确认。修订、审计和 metadata-only Outbox 同事务，Outbox 失败全部回滚。相同 canonical invocation 恢复原提交，不重新调用模型或改写工件；同 generation 的另一命令不得覆盖并发 head。审阅记录追加式，存在数据时拒绝破坏性降级。

## Portal 行为

草稿详情点击“查看断言映射”才加载；按断言显示步骤、预期的前置条件/动作/观察/结果及决定理由。支持历史选择、独立确认、改判与撤回，理由/决定/head/重新查询变化均使确认失效。未知提交结果先查历史，不自动重发。

浏览器验证完整 request/proposal/artifact SHA-256、固定 generation/context/scope、历史链和重新推导的 coverage，不信任响应中的通过计数。读取出错或完整性不符会锁定并隐藏父级草稿，需显式重新核验生成访问权限才恢复。轻/深色沿用 shared tokens，窄屏 oracle 改为单列，无新增可见滚动条。

知识页已增加独立 reviewer 队列，不依赖管理员模型配置或生成 job 读取，也不要求当前 publication head 才发现历史草稿。初始折叠且不读取目录；显式展开后默认三条，后页由用户加载。选中才读取并校验精确 context/scope/generation 工件，复用同一草稿与映射组件。刷新、翻页读取异常、原来源撤权、错误 pin 或归档 hash 不符均隐藏受保护列表/草稿并使确认失效；需要显式重新核验。管理员生成历史中的原入口保持兼容。

独立队列复用既有知识面板的细边框、圆角、主题背景及按钮交互，不依赖被移动掉的父容器 CSS。浅色/深色/390px 浏览器检查同时验证按钮计算样式和无横向溢出；完整归档验证的延迟仍需优化，不能把较长测试等待时间视为 p95 门禁通过。

## exweb 与剩余范围

固定 exweb 快照的三来源、已归档 context/scope/generation、真实 PG 和 MinIO 是验证底座。独立合成 reviewer 的混合决定、改判、恢复、历史及来源/依据变化测试证明契约；它不是 exweb 维护者业务批准或独立 gold。浏览器 generation/review transport 为显式协议夹具，不调用外部模型、执行 exweb、安装 Maven 依赖或声称测试通过。

0064 已实现完整模型分包/多响应原子归并，0065 已实现独立完整多批恢复；v3 和 v4 进入独立 canonical 映射已有 PG 专项证据，当前共享归约器兼容复验的终态见实施记录。不能将单次或三批审阅测试当作完整多批容量验收。

现有 v1 `MappingReviewInput.mappings` 与 `MappingReceipt` 计数上限为 8192，内部 v3/v4 结果最多 32768 cases；用例可以包含多项断言，所以两者容量并不等价。超出限额不能截断后声称完整批准。[完整分片协议](./mapping-partitions.md)已实现确定性计划、逐片校验/完整归并、重新授权的只读接口、0066 私有分片追加式暂存和完整集合独立确认的 v2 映射。暂存不计 assertion_mapped；Portal 编辑/独立确认已接入并有协议专项验证，实际 PG/canonical/MinIO 最终写链另行验证。固定 exweb 新 v2 长测和最新全量组合回归尚未通过，端到端容量/性能仍未验收，实际测试范围见实施记录。

五用途 ContextPack、脚本/RunPlan、真实目标执行反馈、旧链切换、Provider 全生命周期/对照、独立 gold、查询性能与最终 V1 门禁仍属于原目标。独立 reviewer 入口和 Agent 查询不是完整 P5 完成证明。

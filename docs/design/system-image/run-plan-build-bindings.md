# 执行计划与原生构建的固定关联

更新：2026-10-10。0103 增加独立、追加式的 RunPlanBuildBinding，将原执行计划与已经提交的原生构建归档关联。它不改写 v1 RunPlan，不重新构建，不核验目标环境或测试数据，也不授予执行、覆盖或发布权。完整目标仍按 [P0-P6 交付要求](./delivery-and-evaluation.md)验收。

## 固定输入和准入

输入固定 `project_id / run_plan_id / run_plan_artifact_hash`、全部 `native_builds`、一个明确的 `target_build_invocation_id` 和 reason。每个构建引用携带原 invocation、build ID、receipt digest 和 artifact hash；这里的 artifact hash 是原私有构建归档的摘要，不是 JAR 字节摘要。JAR 字节摘要单独从核验后的 receipt 读取。

Application 通过原 RunPlan 和 NativeBuild 读取端口回读，而不是跨领域操作 repository 或读取本地工作区。原计划的全部用例、动作、oracle、审阅和画像历史继续完整核验；全部需求和历史测试来源也继续参与访问检查。原构建端口回读私有源码、JAR/日志归档并核验原字节和登记摘要，绑定层不接受客户端提交的 receipt 正文。

每一份原画像已采集的代码来源都必须对应一份原构建。同一 project/image/hash/manifest/hash、完整 binding/source revision 集合必须精确一致，缺项、额外来源、重复来源、错修订或仅有 reservation 的构建均拒绝。多个代码源不能因一个主 JAR 成功就被当作全范围已核验。

主构建的 JAR 文件名、字节 SHA、构建定义 SHA 和工具链必须与原计划声明完全一致。v1 明确定义构建定义 SHA 为原归档根 `pom.xml` 的 SHA；它不是完整 Maven profile 或外部依赖供应链摘要。完整文件清单另以摘要固定，原构建 receipt 固定全部实际文件、请求及工具链。当前只接受 Java 21 / Maven 3.9.11 的离线只读依赖缓存适配器；其他语言/构建器需要独立版本化 port 和 policy，不能伪造 Maven 回执补齐来源。

完整绑定超过 4 MiB 时拒绝，不截断来源。只在单次编译内复用已核验的不可变画像元数据，当前 ACL、审阅和上游有效性仍重新检查；提交回调使用新的编译，复用不跨请求，也不是持久授权。

## 公开入口

`POST /v1/projects/{project_id}/quality/run-plan-build-previews` 和 canonical `query.quality.run_plan_build_preview` 只预览，返回 exact request、binding/source-scope digest、完整来源数及剩余门禁，不调用模型或 builder。

写入仅通过 canonical `quality.run_plan.bind_native_build`，需要当前 qa_lead/project_admin/platform_admin、完整来源权限，以及同账号对原完整请求的独立确认。命令必须 running；确认时间带时区、不在未来且不超过 15 分钟。新写入在归档前及 PG 提交时验证。字段、来源权限摘要或上游有效性改变后须重新预览与确认，不能沿用旧确认。

`GET /v1/projects/{project_id}/quality/run-plan-builds/{binding_id}` 在重新授权原计划和全部原构建之后才读取私有绑定归档，核验内容及登记摘要。canonical `query.quality.run_plan_build` 仅返回元数据及当前使用状态，没有源码、日志、私有地址或完整 receipt。Agent 再次使用查询结果时重新回读；撤回导致旧回执不再匹配，指纹也改变，不把它当作执行许可。

原审阅撤回后绑定历史及原 v1 计划保持不变，但 `inputs_current=false`，新的绑定预览拒绝。已提交命令原恢复只回读，不要求重新确认，不重建或重新调用模型；来源撤权或归档损坏仍拒绝。HTTP 使用 `private, no-store`。

三个 canonical 工具的单项、列表、resolve 和 Agent 回执读取均重新授权完整原计划及全部原构建；不是只检查项目成员或关联元数据。会话发现、搜索和 Conversation/Goal/Swarm SSE 只展示脱敏生命周期，不广播输入、来源、构建回执、理由或私有地址。历史事件也执行同一只读投影，不依赖今天仍有实体、不修改原 Outbox。HTTP 拒绝和服务异常同样保留 `private, no-store`，不泄漏内部归档信息。

## Portal 操作

已审阅脚本的 RunPlan 详情提供折叠的构建关联表单，明确要求每个原代码来源的 native build invocation ID、主目标和关联理由。展开后才加载，完整回读原计划、全部来源和每份原构建，再核验预览。修改输入或重新查询使勾选确认失效，保存走 canonical 确认，不直接上传绑定正文。

创建前保存同账号、项目、计划和摘要范围内的元数据恢复指针；创建或确认回执丢失后仅 GET 原命令及原归档，不自动重新提交。恢复的待确认命令仍要求用户重新勾选，历史审阅撤回后只可查看原绑定，不允许新绑定。light/dark 和窄屏沿用共享样式，无可见滚动条；协议浏览器检查不代替原生 PG/MinIO 写入或实际 Java 编译。

## 持久化和事务

`quality_run_plan_build_bindings` 保存固定计划、主目标、绑定及归档摘要；`quality_run_plan_build_members` 保存完整代码来源及各原构建摘要。复合外键连接原计划的确切 project/ID/hash/plan digest/image/manifest，以及每个原 reservation/result 的确切来源和归档/receipt 摘要。延迟外键要求主目标确实属于此次完整成员集合。

0103 使用固定 DDL，只为旧父表添加确切组合的 unique constraint，不改写旧记录、旧工件或旧 schema 摘要。新两表禁止 UPDATE/DELETE，非空记录阻止破坏性降级。事实、成员、审计和 metadata-only Outbox 在同一个项目锁/PG 事务提交；归档期间撤回、错父项、缺成员或晚期 Outbox 故障回滚新数据库事实。MinIO 不参与 PG 事务，未引用归档仍需后续受控 GC。

正常读取、查询回执恢复和事件核验只验证历史，不补造缺失成员，也不把今天的新审阅或新构建改绑到旧记录。

## 当前边界与验证

绑定中的 `native_build_source_attested=true` 仅说明原归档源码字节和已提交构建产物匹配。`source_file_modes_attested / reproducible_build_verified / dependency_supply_chain_verified` 保持 false；原计划仍保持 `declared_not_native_verified`，新状态只存在于独立绑定。environment/locator、fixture setup/cleanup、独立执行授权和 canonical 逐 case/step/oracle 运行是剩余门禁，所有执行/通过计数仍为零。

纯测试覆盖完整多源输入、原文/计划不变、原始摘要、目标和工具链、缺源/错源/缺产物/假布尔/伪覆盖、字节预算及当前权限。PG/MinIO 测试覆盖 canonical 确认、实际 FK/schema、不可变及降级保护、历史撤回、查询重验、确认时效、晚期 Outbox/审阅回滚和原构建损坏时拒绝私有绑定读取。迁移兼容检查在 rollback-only 事务中还原新表为空的 0102 边界、保留已经提交的旧计划/构建数据，再执行 0103 固定 DDL；比较全部原父行，并在恢复 schema 后回读原 PG/MinIO 工件，不把空库升级当作 populated upgrade 证据。

固定 exweb 专项在自己的完整单代码源画像上使用原 126 个 Git blob、实际无网络 Docker Maven 构建和私有 MinIO 原产物回读，再通过同一 canonical 确认关联。模型/调度 transport 和需求/oracle 仍是明确的协议 specimens，不是维护者批准的业务 gold、外部模型质量、Temporal 恢复或目标执行证明。各测试是否实际通过与报告范围以[实施记录](./implementation-progress.md)为准，不用测试定义替代证据。

生产 Portal 已有 RunPlan 声明与原生构建关联表单；固定画像还提供独立的原生构建入口，详见[原生构建](./native-target-build.md)。旧 `run.start` 尚未切换，也没有已验证环境、数据 fixture 或逐用例目标执行。独立 gold、多语言、五用途 ContextPack、自动 delta/失效 DAG、治理终态原子链、安全、性能、容量与试点仍是原完整目标的必需交付。

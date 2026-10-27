# 原目标环境观察的独立登记

更新：2026-10-11。0105 增加追加式 PostgreSQL 环境观察事实和完整私有 inventory 工件。它不是部署事实、当前环境租约或正式执行授权；与原[只读环境查询](./native-target-environment.md)分开。

## 命令与输入

- `quality.run_plan.record_environment` 经过 canonical ToolInvocationRuntime 的独立 `user_confirm`，要求当前 qa_lead/project_admin/platform_admin 和全部原来源访问权。输入仅为 project_id、run_plan_id/run_plan_artifact_hash、build_binding_id/build_binding_artifact_hash。不能传入 URL、容器、运维文件路径、inventory、开发探针 JSON 或自报核验结果。
- PG 在任何 Docker 工作前验证原 running 命令、确认主体、精确请求、项目归属和 15 分钟确认 TTL；提交时重新检查。计划准备、原生构建或构建关联的确认不会转移到这个动作。
- 通过原计划和构建的应用读取端口检查固定 image/manifest/JAR 和当前原输入，再调用原生环境 port。实际运维 registry 与原计划政策摘要一致，检查前后 resource metadata 和实际挂载 JAR 摘要不变。没有部署、业务 HTTP 请求、模型调用或 Runner 派发。

## 私有归档与正式事实

私有工件 schema 为 `nasus.run-plan-environment-record.v1`，保存精确原请求、计划/画像/来源清单/构建/JAR/政策 pin、原完整 `NativeEnvironmentObservation`、确认命令与主体和时间。完整 inventory 的 content digest 与 observation time 独立保留，不能用一份工具结果 JSON 替代。工件使用项目命名空间和内容寻址，最大 128 KiB；写入后及 PG 提交前回读核验。原始字节与所有正式引用保持不可变。

`quality_run_plan_environment_records` 固定原计划和构建关联的复合 FK、唯一 invocation、工件 ref/hash、inventory hash、政策和 JAR hash。原事实、审计与 metadata-only Outbox 同事务。晚期失败不得留下半份成功事实；私有对象写入与 PG 不是分布式事务，未登记的孤儿工件清理仍为待交付项。

不把旧查询 JSON 或独立 exweb 探针报告回填成新事实。0105 初始为空；已有 0103/0104 历史不改写。新表拒绝 UPDATE/DELETE，已有事实时拒绝降级丢弃历史。构建父表只新增复合唯一约束，不补造历史环境核验。

## 读取、重入与 Agent

- `GET /v1/projects/{project_id}/quality/run-plan-environments/{record_id}` 是受保护的完整私有读取，设置 `private, no-store`；失败响应同样设置。先验证项目 reviewer、原 canonical 祖先和全部来源访问权，再读取 inventory 字节。核对原请求、工件 hash、原生 observation schema/hash、记录身份、父摘要及 PG 元数据，返回前重新授权。
- `query.quality.run_plan_environment_record` 只返回 metadata，不返回容器 ID、命名空间 URL、完整 inventory 或对象存储地址。当前权限撤回、坏原父、坏工件或回执错绑均拒绝。完成工具回执、批次列表和 Agent describe 重新对照独立事实，不因历史不可变跳过即时授权。
- 已提交命令重入回读原事实，不再次读取 registry 或操作 Docker；原输入后来 stale 不会重写历史。新登记仍要求 current 输入。未提交动作没有自动重试或部署恢复能力。
- 共享 Conversation/工具事件只展示脱敏生命周期。环境事实事件只含 project/record/plan/inventory hash/status，重放在原 PG 会话核对事实、全部祖先和原命令 envelope，不补写、修复或读取 Docker。

## 权威边界

新登记回执的 `durable_native_observation_verified=true` 仅表示完整原生观察已独立归档、登记并可回读核验；`historical_not_live=true`。原 v1 只读查询仍保持 durable=false，schema、字节和含义不变。

`environment_fully_verified / execution_authorized / external_egress_denial_verified / host_access_denial_verified / dependency_health_verified / fixtures_verified / locators_verified / business_coverage_verified` 均为 false，正式 automated/executed/passed 均为零。环境配置检查、原 JAR 和独立持久化不是物理拒绝/依赖健康、fixture/locator、目标执行许可或 case/oracle 的业务覆盖证明。

## Portal 独立审阅

原 RunPlan 构建关联面板增加默认收起的环境登记面板，复用共享边框、按钮和明暗主题。只有明确为 local、原 origin 为 `http://127.0.0.1:8080` 且当前原输入通过检查的计划才能登记；test 环境声明不能自动升级为运维自有目标。每次新登记均要求新的独立勾选，计划、构建或上游审阅变化后清除原同意。

创建或确认回复丢失时，恢复仅 GET 已知原命令；不重发写入。sessionStorage 只保留账号、项目、计划、关联、原命令 ID/hash，不保存 URL、完整 inventory 或凭据。历史 GET 对完整归档及 metadata 做严格类型、身份、父 hash、inventory digest 和权威边界核验；坏归档、403 或 502 隐藏旧敏感内容。完整原 inventory 默认折叠，只有受保护的详情读取可以展开；历史有效不代表当前可执行。

## 验证与剩余范围

纯领域/应用测试覆盖原 inventory 保存、确认先于原生工作、撤权/父变化/坏归档禁止提交、当前权限先于私有字节、旧事实无 Docker 回读、严格类型与回执完整性、Agent metadata 和共享脱敏。PG/私有 MinIO 专项使用真实 canonical 原计划/构建登记及审计/Outbox；模型、构建产物和 Docker metadata 明确为 protocol specimens，不能冒称真实 exweb 部署或业务 gold。

固定 exweb 的实际 runtime 报告仍见[真实运行验证](./exweb-native-runtime-validation.md)，不将开发探针 JSON 导入正式环境事实。新的原生专项从 canonical 保存的原 JAR 启动自有目标，再调用生产 registry/inspection 适配器登记完整原环境，并在资源删除后核验原历史；只有专项终态通过才证明该链，其模型和业务规范仍是明确的 protocol specimens，不是维护者业务 gold。最新结果见[实施记录](./implementation-progress.md)。物理出网/宿主拒绝、依赖健康、fixture/locator、独立执行授权、持久派发/取消/恢复、正式覆盖回流、完整五用途与 P0-P6 门禁继续交付。

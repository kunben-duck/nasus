# 原目标环境与挂载产物的只读核验

更新：2026-10-10。已接入 canonical `query.quality.run_plan_environment`。它核验已保存 RunPlan 对应的原构建产物和运维登记资源，不部署目标、不派发 Runner，也不是完整环境准入或正式执行验收。

## 输入、权限与分层

公开输入严格限制为 `project_id / run_plan_id / run_plan_artifact_hash / build_binding_id / build_binding_artifact_hash`。不能指定 container ID、网络、URL、宿主路径、内联 inventory 或覆盖状态。工具需要当前项目 reviewer（qa_lead/project_admin/platform_admin）和完整原输入的来源权限；低风险只读不等于 viewer 可以访问被保护源码的派生信息。

Application 经现有 RunPlan 和构建关联 application port 回读全部原祖先和私有工件，核对项目、计划/构建关联 ID、工件 hash、plan digest、画像、来源清单和原 JAR hash。新的实时核验要求 `inputs_current=true`，不把历史输入视为当前授权。操作内只读会话可以复用不可变祖先，权限仍在开始、Docker 子命令、完成及返回前检查；没有跨请求缓存或 ORM/Docker 进入领域层。

`NativeTargetEnvironmentPort` 隔离 Docker。`OwnedEnvironment` 固定运维资源身份；`NativeEnvironmentObservation` 严格校验完整字段、摘要、UTC 时间、非 root 用户及明确的能力限制。`ConfiguredOwnedTargetEnvironments` 是当前基础设施实现，后续容器栈更换不应改变公开领域 ID。

## 运维登记

`NASUS_TARGET_ENVIRONMENT_REGISTRY` 默认为空，空值或坏文件拒绝核验，不自动选择 Nasus 开发容器。启用时为绝对路径、当前服务账号拥有的普通 JSON 文件，仅本账号可读写（建议 0600），不能为符号链接。读取上限 256 KiB，重复 key、非有限数、未知字段、资源重用和读取中变化均拒绝；不缓存文件。

顶层只有 `schema=nasus.owned-target-registry.v1` 和 `environments`（1–32 项）。每项为 `OwnedEnvironment` 的精确字段：

| 字段 | 运维登记内容 |
| --- | --- |
| project_id、environment_id | 原项目和原计划选定的环境 |
| owner、prefix | 16 位十六进制 ownership token，以及 `nasus-target-{owner}` 或 `nasus-exweb-{owner}` |
| container_id、image_id、network_id | 实际完整容器/网络 ID 和不可变 `sha256:` 镜像 ID，不是名称或 tag |
| dependencies | 恰好 `role=pg`、`role=redis` 两个不同容器；每项含 role/container_id/image_id/user，user 为实际非 root 数字 UID:GID |

网络和三个容器都必须具有 `nasus.target.environment_owner` 的原 owner 标签及预期名称，资源只能属于这一登记。计划 environment 的 `inventory_hash` 必须等于该领域值的 `digest`（固定序列化字段计算的 SHA256），不是 JSON 文件的原始字节 hash。计划原 URL 固定为容器命名空间内 `http://127.0.0.1:8080`，它不是宿主开发 API。

这份文件不保存凭据，也不创建资源。修改登记不会改写旧计划；新实时核验需要原计划明确固定相同政策，不能用“最新登记”替换旧输入。现阶段没有部署写 API、自动环境恢复或可导入任意核验结果的接口。

## 实际核验内容

核验容器的完整 ID、镜像、ownership、名称、running 状态、启动时间和用户；目标必须以 65534:65534、只读根和只读 `/app/target.jar` 挂载运行 `java -jar /app/target.jar`。依赖以登记的实际非 root UID:GID 运行。三个容器都限制 memory/CPU/PID，移除全部 capabilities，禁用提权/privileged/host namespaces 和宿主端口。

网络必须是本机 bridge、internal、非 attachable，且成员恰好为目标、postgres、redis。目标只允许只读 JAR bind 和 `/tmp` tmpfs；依赖只允许各自精确的数据 tmpfs，不能夹带宿主卷。实际 Docker 将 `--tmpfs` 保存在 `HostConfig.Tmpfs`，`Mounts` 可能为空；核验两种元数据表示的契约，而不是要求 Docker 一定报告 tmpfs mount 项。

在目标容器中计算实际 JAR SHA256，与原构建关联精确比较；前后容器/网络元数据必须不变。命令有取消、时间和输出上限，授权异常保留原语义。metadata projection 不读取 Config.Env，不保存 JVM 尾随参数；不会把数据库密码或模型 key 写入回执。

这些检查是运行产物及选定隔离配置的观察。Docker 的 internal 标记不能单独证明物理出网或宿主访问被拒绝；进程 running 也不是数据库业务健康或 fixture 正确。

## 回执与历史读取

回执只有原 query、环境 ID、inventory/政策/JAR 摘要、时间和有界状态，不返回容器 ID、地址、原文、命令或凭据。`native_artifact_attested=true / isolation_configuration_attested=true / historical_not_live=true` 只限本次观察。

`durable_native_observation_verified / environment_fully_verified / execution_authorized / external_egress_denial_verified / host_access_denial_verified / dependency_health_verified / fixtures_verified / locators_verified / business_coverage_verified` 始终为 false，正式 automated/executed/passed 为零。剩余门禁显式列出，不允许遗漏。

普通回执 GET/list 与 Agent describe 核对完成状态、原 invocation 归属、严格回执字段及原计划/构建关联。历史读取重新检查当下角色和来源权限，不重新检查 Docker，不要求登记文件或目标容器仍存在。批次在同一只读会话核对祖先，再重新核验当前 ACL；任何损坏的已授权回执使列表整体报完整性错误，不能吞掉后声称没有记录。共享会话及持久工具事件只展示脱敏生命周期。

这个只读查询不保存完整 native inventory 的独立私有工件/PG 环境事实，所以其格式合法的 inventory hash 尚不能通过独立归档重算。ToolInvocation JSON 不是签名或独立持久环境证明，false 的 durable 标记保留这一边界。后续新增的[独立归档登记](./native-environment-records.md)使用另一个需要确认的 canonical command，不修改此查询的 schema 或权威。历史回执也不是当前 Docker 租约。

## 验证与后续

协议专项覆盖身份、原 hash、容器重启、资源/挂载/网络变化、registry 读取、权限撤销、历史不重新核验和回执权威升级拒绝。PG/API 专项使用真实账号、项目、来源 ACL、canonical Runtime、SQL 回执及 Outbox，但 saved parent 与 Docker metadata 明确是协议 specimens，不声称已保存真实部署链。

固定 exweb 的独立开发运行已使用同一生产 inspector 在实际目标业务检查前后核验；真实 Docker 的 tmpfs 表示是修正依据。19 项开发检查中 13 项通过、6 项失败，记录在[真实运行验证](./exweb-native-runtime-validation.md)。它不是维护者批准的 oracle 或正式业务覆盖。

完整部署事实/私有 inventory 归档、物理出网与宿主拒绝、依赖健康、fixture/locator 验证、独立执行授权、持久派发/取消/恢复和逐 case/oracle 的正式覆盖回流继续属于原 P0-P6 目标。本次只读能力不代替这些交付，也不修改旧 `run.start` 的执行链。

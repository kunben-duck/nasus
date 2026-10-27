# 原实例 HTTP 执行端口

更新：2026-10-12。该端口推进 P5 的真实目标执行适配，不是独立执行批准、公开 RunPlan 派发或完整闭环交付。它不改变原 0101/0105/0106/0107 记录及其零覆盖语义。

## 边界与固定输入

`OwnedTargetHttpRunnerPort` 属于 quality_loop application，输入为原 `AutomationRunnerCommand`、environment ID、原 artifact hash、原 inventory hash 和每次调用都有效的 `require_work` 回调。输出保留原 request/result bytes、经过完整原响应验证的结果，以及环境 ID/hash，不返回 fixture 或业务 authority。

`ConfiguredOwnedTargetHttpRunner` 是基础设施防腐适配器。它只从 operator 私有 registry 选择当前项目的确切资源，复用 `ConfiguredOwnedTargetEnvironments` 和生产 inspector；HTTP body 不能选择 container/image/network ID、registry 文件或 Node CLI 路径。registry 必须是本账号拥有、无 symlink、0600 的有界完整 JSON，重叠资源和不明字段拒绝。显式 operator 构造时可以固定 registry 路径，默认仍使用原环境变量；不增加 public API 或 Tool ID。

当前适配能力限定为已隔离的 local Spring Boot/Java 目标及其原 PG/Redis cohort，namespace origin 必须为 `http://127.0.0.1:8080`，HTTP v1/v2 原协议兼容。其他语言、目标类型、browser DOM、远程环境和正式 fixture 生命周期仍需独立适配，不静默走 host HTTP 或其他 Runner。

后续[HTTP fixture 生命周期模块](./http-fixture-lifecycle.md)已消费该 port，分别执行显式准备
及按原资源 ID 的清理，并核验原 wire/response；固定 exweb 原生专项已有证据。
该模块目前仍缺生产 PG journal、独立执行/清理批准及公开 canonical/Temporal 接入，
不能把私有探针文件 fence 或 cleanup_verified 当作正式执行授权、整体基线恢复或业务覆盖。

## 实际执行

1. 独立应用授权/owner 回调有效后，编译完整原 job wire，不重排 body、替换 oracle 或省略 case 动作。当前新端口要求调用者提供回调；它不是可以自行产生批准的授权服务。
2. 执行前生产 inspector 重新验证原 registry、JAR 和原 inventory hash；容器重启即使 image/JAR 不变也不能沿用旧输入。
3. 私有 `owned-http-cli.mjs` 仅接收显式内部 flag 和完整有界 stdin envelope。原 wire 以 canonical base64 保留，CLI 校验 project/HTTP scope 后调用现有生产 `executeHttpJob`，不通过公开 `/v1/jobs` 选择 Docker transport。
4. `owned-http-cohort.mjs` 对原 target 和 PG/Redis 的 ID、image、StartedAt、owner、non-root 用户、资源上限、capabilities、rootfs/mount、namespace 及唯一内部网络成员进行完整复核。Node/Python 使用相同的 credential-free inspect format，不读取 Config.Env 或 JVM 的敏感尾部参数。目标、网络或依赖在任一次请求前后变化都拒绝，不能只在任务开始检查一次。
5. 请求使用目标内 curl 访问自身 loopback，保留原 POST 字节和非 2xx 响应；不读代理配置、跟随重定向或自动重试。正常结果保留原 manifest、每个响应体/metadata 和断言结果，后端重新核验全部物理响应，再验证同一完整 inventory。
6. worker 子进程通过 anonymous stdin file 避免大输入/输出管道互相等待；输入/输出、时间均有界。运行期间反复检查应用回调和 registry，失去权限/owner 不被结果校验隐藏；子进程组停止后不重发未知写操作。

Docker 客户端停止不证明远端 curl 已即时退出；已经发出的请求可能产生业务效果。curl 自身有五秒上限，但仍需要后续正式 RunPlan owner/lease、取消与未知效果恢复协议。校验失败不会返回可信成功或切换其他实例；当前端口没有持久的部分结果恢复能力，不能冒充 durable lifecycle。

## 原始归档与回放

固定 exweb 开发探针现在直接调用该 application port；私有临时 registry 自动清理，不改变开发服务或数据库。实际 fixture、oracle 仍是 `developer_probe_not_approved_specification`，不是正式批准的 AC，也不是 canonical RunPlan。报告记录同一任务输入的完整 inventory/hash、全部原 request/result 文件和当前执行器源文件摘要。

`scripts/verify-exweb-owned-http-archives.py` 在目标清理后只读核验固定仓库的完整 126 个 Git blob、原七个任务及全部响应、原 inventory、执行器代码摘要和原失败结果，不再次 Docker/HTTP。source inventory 的三个身份字段和导出时添加的原字节 hash 分开核验，不能把合法 enrichment 当成版本变化；所有文件都验证，不只取样。

回放成功表示历史字节与原断言结果可核验，不表示业务检查通过；报告始终区分 `passed_jobs/failed_jobs` 和 `formal_coverage_verified=false`。本地报告不能导入为执行批准或生产覆盖证据，不能与另一个 JAR/PG 批次的 canonical 来源事实拼成已完成闭环。

本轮真实运行和失败分母见[实施记录](./implementation-progress.md)。完整 fixture/runtime locator 核验、独立持久执行授权、canonical Tool/Temporal dispatch、取消/恢复、PG/MinIO 原子证据及真实覆盖到放行继续按完整 P0-P6 要求交付。

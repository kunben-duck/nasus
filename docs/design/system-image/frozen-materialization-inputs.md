# 固定来源的兼容上下文构建

状态：2026-10-10 实现；0096 新增原命令的持久来源输入。本切换属于 P1 的来源消费与旧链清理，不代表完整 P0-P6 已交付。验证终态见[实施记录](./implementation-progress.md)。

## 原问题与消费边界

旧 `SystemImageService.materialize_context` 先执行无原 canonical invocation pin 的 `ingest_sources`，再选择 latest manifest。已经采集的来源仍会被读取，新增 binding 会隐式采集；一个可选来源失败还会绕过固定候选准备，退回可变 RawAsset 提取。注册、采集、提取职责并未实际分开。

现由 `MaterializationInputApplicationService` 只读准入现存 manifest 与当前完整来源权限，要求所有选中代码均已 captured、完整 manifest hash 正确且成员等于当前注册集合。无清单、未采集代码、新增 binding、缺依赖或损坏历史均明确拒绝，不调用 connector、不修补来源、不使用 legacy mutable 提取。用户必须先提交独立 `system_image.sources.ingest`，再构建。

可选 `failed` / `pending` / `legacy_unverified` 成员仍留在原固定清单中作为缺口；只从 captured SourceRevision 读取文件，不重新尝试失败来源，不凭路径制造内容。代码必须，需求和历史测试可选的边界不变。

## 阶段检查与派生数据

- 使用现有 source authorization application port 检查完整项目来源、原 scope fingerprint；读取归档前后、每个提取阶段、候选冻结前和 mutable 投影应用前都复查。来源撤权不是普通采集缺口。
- 候选准备、后续 raw chunks 与兼容 embedding/rerank 消费本次固定 sources，重建 chunks 时不混用工作区的可变 content_ref。embedding/query-embedding/rerank 返回后再检查权限与来源头，撤权不继续后续模型阶段。
- 构建不再把 code-analysis / Provider 证据追加回 RawAsset，来源采集事实不改变；代码证据保留在具体对象、注册修订和分析工件中。
- 原文件被修改、删除或 connector 不可用不触发补采。归档损坏/不可用必须失败，不回退到原路径；公开回执仅包含固定脱敏错误码和摘要。
- 提取期间其他独立命令推进来源头，当前构建拒绝，不用旧工作区快照覆盖另一命令的新来源/chunks。其他失败保留既有兼容回滚行为；先前合法追加的候选工件不因后续 embedding 失败被改写成批准事实。

后续负测确认，新增 binding 后原权限 fingerprint 失效，旧异常分支仍会回滚并覆盖其他 canonical capture 刚提交的来源和 chunks。现在每次补偿前核验原完整来源头和 roster；来源变化或核验不可用均不写回旧 snapshot。真实 HTTP/PG/MinIO 同时覆盖权限范围变化与 Provider 异常两分支。没有通过放宽授权或只检查错误文案绕过新来源保护。

这些阶段检查不是覆盖 PG/MinIO/Provider/兼容投影的单一事务。来源头变更与最终投影提交仍需要更完整的 owner fencing / CAS 交付协议，不能仅凭前后检查或补偿保护声称并发原子性。

## 构建与工具调用的工作区寿命

移除隐式 ingestion 后暴露了旧工作区寿命问题：`ContextVar` 传播的是同一个可变 snapshot 字典，不是独立请求缓存。此前一次主线程直接操作即可让后续 HTTP 命令沿用旧 US 列表；仅隔离 materialize 又会让随后质量工具用旧 snapshot 覆盖新 TaskContext。

现在 canonical Runtime 通过必需的 application `ToolOperationScopePort` 在每次实际 handler dispatch 前进入独立工作区；生产 composition 注入 `SQLAlchemySystemImageWorkspace.operation_session`，平台不导入 ORM、具体工作区或 ContextVar。每次分配新的 staging 字典，结束、异常和取消均恢复调用方上下文。materialize、兼容 initialize 和画像查询也有独立 scope，直接调用不借用父请求暂存事实。等待确认、拒绝和幂等回执读取不进入 handler scope，不新增执行。

私有 `_materialize_context` 的 manifest、prepared candidate 和 phase check 均为必需参数，不再保留 `prepared=None` 时从 mutable RawAsset 抽取的分支。原归档损坏、撤权或 head 冲突不会通过这个私有入口降级。

该 scope 不提供数据库锁、事务、访问授权或跨进程 owner。仍使用已有显式 persistence；父级未提交 staging 不被丢弃或提交。其他未进入 canonical/application scope 的兼容工作区调用与完整质量入口切换仍需继续清理。

## 原 canonical 命令的持久来源输入（0096）

生产 composition 注入独立 `MaterializationCommandInputPort`。领域值对象固定 invocation/project/执行账号、canonical command hash 以及 manifest ID/hash，application 只调用端口，不导入 ORM。`materialization_source_inputs`、原 ToolInvocation 的消费 hash 和 metadata-only Outbox 在同一 PG 事务、共享来源锁下提交，发生在提取之前。表及非空消费 pin 不可修改/删除；丢失或损坏原输入拒绝，不借 retained SSE、latest manifest 或另一个采集命令补造。

恢复先读取原 pin，再回读确切原清单，随后核验当前 source head/完整 roster、实际持久账号、项目角色及来源 ACL。新增清单不能替换旧 running 命令的输入；必须独立新命令。第一条与恢复命令都要求实际 running 的 `system_image.context.materialize` 或已确认的 `system_image.baseline.initialize`。生产无 invocation 的直接物化明确拒绝，`us.task.start` 也不再隐式直接构建，缺画像时由独立 canonical follow-up 提出。

迁移在锁住 ToolInvocation 创建的窗口登记所有旧物化/初始化命令到 `materialization_legacy_commands`，不推断旧原输入。旧 completed 的 canonical 结果历史不变；旧 running 需要独立新命令，不能用当前清单补 pin。迁移与 populated downgrade 有独立真实 PG 前后验证。

实际两个 OS 进程验证原输入提交及候选提交后 SIGKILL、新 PID/私有缓存恢复；当前撤权与他命令推进 head 拒绝。exweb 原清单固定 126 Git blob，删除全部导出目录后新进程仍读原 MinIO 字节，零 connector。它是显式内部恢复验证，不是生产自动扫描、Temporal dispatch、owner lease/取消或 canonical 终态原子提交。

本 pin 只覆盖来源输入，不固定全部 project name/baseline/version/兼容模型配置。候选和兼容投影、ToolInvocation 终态也不是一个交付事务；同原输入重试可能重新准备候选/embedding，不声明 stable output 或 exactly-once。0094/0095 的采集 intent/result 属于采集命令，不能代替独立物化输入或授权。

## 验证范围与未完成项

真实 HTTP/PG/私有 MinIO 负测复现旧隐式采集；验证独立首次采集、新增未采集 binding 拒绝、可选失败仍走 frozen 提取、读取前/后及 embedding 返回后撤权、独立命令推进 head、归档损坏/不可用、原文件删除后构建零 connector。

exweb 固定已审查 Git commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 的 126 个 blob。导出目录完全删除，新缓存从私有 MinIO 重建，全部原文件字节验证一致；canonical materialize completed，原 source facts 与 manifest 不变。该验证使用当前本地代码适配器，不冒称 native Provider、真实远端 Git 重采、业务语义 gold、外部模型或 exweb 目标执行。

兼容 `baseline.initialize`、旧 TaskContext/QualityProfile/US 同步、受限条数的旧 embedding/rerank、全部旧质量入口仍未完成正式 ContextPack/发布链切换。candidate 不授予 independent AC/BR authority、生成/执行许可或正式 publication。自动采集 dispatch/lease/取消、完整累计模型费用、五用途、自动 delta/invalidation/overlay/merge、真实 oracle/执行/证据回流和容量/性能门禁继续保持完整目标要求。

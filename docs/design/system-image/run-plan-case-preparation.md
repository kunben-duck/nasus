# RunPlan 独立业务命令的持久认领

本阶段补齐 P5 的原命令认领记录，不代表公共执行入口、Temporal 恢复或业务覆盖率
已经交付。完整方案仍以自主系统画像主方案和交付门禁为准。

同日后续新增 [0120 任务生命周期](./run-plan-case-jobs.md)，连接 canonical 工具、
原命令 Temporal 调度、独立取消和重新授权的历史读；真实外部依赖验证和 Portal
仍未完成。下文描述的是 0119 认领本身的边界，不把认领当成执行结果。

## 原记录关联

`ToolInvocation` 进入 `running` 时，在相同 PostgreSQL 事务中写入
`quality_run_plan_case_preparations`。记录固定 invocation、project/run、完整 selection
digest、完整命令 digest、独立确认人、确认时间和 PG 认领时间。selection 必须保留
原 RunPlan、build binding、environment、locator 和全部 case/setup invocation pins；
不接受客户端 scope、verified 标签、缺少字段或重复 setup/case。

`case_claim_protocol` 由后端认领 hook 写入，客户端输入中被清除；普通查询规范化
时移除该协调字段，但完整命令 digest 必须包含它及所有 Agent/确认协调字段。
来源、项目权限、真实输入核验仍由执行 producer 和既有执行 guard 承担，认领记录
不授予目标操作许可。

首次取得原 case work 时，同一事务写入 work、lease 和
`quality_run_plan_case_preparation_bindings`。binding 固定 preparation digest 和完整
work digest，关联同一 project、run、invocation、actor、原 scope/完整 roster。
之后每次原命令核验同时验证两种 receipt、work 和独立确认链。

已有准备记录不能在 marker 缺失时回退为旧协议；work/binding/receipt 任一不完整
均拒绝继续，读取不补造历史。两张新表都是 append-only，migration `0119` 使用
固定 DDL、不回填旧命令，存在任意记录时拒绝降级。project/run 唯一约束用于防止
两个不同命令把同一次原业务尝试分别认领；并发事务行为还必须在真实 PG 验证。

## 生命周期与边界

- 原始确认按 PG 认领时间校验 15 分钟窗口。历史核验保留原认领时间，不延长确认；
  后续执行仍遵循既有新鲜度、当前 actor/source、target epoch 和 work ownership。
- preparation/binding 的 `execution_authorized`、`business_coverage_verified`、
  `canonical_execution_committed` 均为 false。认领不是派发、测试通过或正式覆盖率。
- `RunPlanCasePreparationRepository.pending` 仅供 worker 的受限分页发现，返回
  invocation IDs，不认领任务、不取得租约、不派发 HTTP。`delivery` 核验记录并返回
  内部状态元数据，不是公开查询或权限绕过接口。
- 原内部无 receipt 的 case 命令保持兼容，但不得被自动提升为可恢复 preparation。
  `ToolClaimJournal` 组合 fixture 与 case 的两种 hook，不能替换旧 fixture receipt。
- domain 只含身份、时间、digest 和关联规则；ORM、PG 时间和事务属于 infrastructure。
  原命令只读 guard 不新增项目写锁或跨 session 递归锁。

## 验证要求

离线测试核验完整七 case、协议 marker 防伪、确认窗口、损坏/丢失记录拒绝、旧终态
只读、不回填、work receipt 绑定、固定 PostgreSQL DDL、FK/unique/trigger/降级保护、
生产组合 hook 和无连接导入。使用显式 PG URL 与事务替身，不等价于真实事务证明。

`test_run_plan_case_preparation_postgres.py` 为真实隔离 PG 环境准备了原命令并发认领、
同 project/run 的不同命令竞争、异常回滚、不可变 trigger、已有记录降级拒绝及独立
空 schema migration roundtrip。Docker 不可用时不收集执行这些测试，更不改用 SQLite。

后续必须验证已接入的公共 Tool/Catalog/RBAC、Temporal 生命周期/取消/重试及原 ACL
下的私有历史读取，完成 Portal、fixture 到业务资源绑定及 unknown 处置，再用固定 exweb 验证实际
PG/MinIO/原生目标执行。正式 coverage/release、五类上下文、旧链切换和 P0-P6 的安全、
gold、性能及试点条件继续必需。

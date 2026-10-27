# 原始测试数据操作的 Portal 入口

更新：2026-10-13。代码接线与协议验证，不代表真实 PG、Temporal、浏览器 E2E 或 exweb
业务链已验收。上游完整计划仍为[开发验收方案](./delivery-and-evaluation.md)的 P0-P6。

## 入口与依赖

知识页的已核验 RunPlan 下，原 fixture 定义归档显示“准备或清理测试数据”。初始折叠，
不读取环境、许可或任务，也不发起操作。组件按账号、原 recipe ID/hash 挂载，复用现有
RunPlan/shared tokens、细边框及按钮；表单在窄屏切为单列，无新增可见滚动条。

用户输入原环境**登记命令 ID**，不是 record ID、URL、容器或外部报告。只读适配器沿原
completed command → 原 build binding command → 全部 native build members → 完整 binding
归档 → 完整环境记录回读并核验。不能只相信环境 metadata、binding hint 或缺少成员的
构建摘要。所有 HTTP 读取 private/no-store；Abort 不发出操作或确认请求。

原计划/recipe、环境实例库存、operator policy、JAR、源码版本与来源清单分别固定，
实际 inventory hash 不替换为 operator policy digest。传入表单的 env command ID 不允许
改目标 URL 或执行请求。环境读取是历史回放，不刷新目标健康或生成新观察记录。

## 独立确认链

1. 选择 `setup / cleanup`、有界 timeout 与 attempt ID，对照原 recipe 和环境核验请求。
2. 独立勾选后通过 `quality.http_fixture.authorize` + ToolRuntime confirmation 保存显式
   v2 限时许可。scope、原环境 record/hash、确认人、PG 时间和15分钟寿命保留。许可不是派发。
3. 许可回执与私有 GET metadata 完整一致后，另行勾选、确认
   `quality.http_fixture.execute`，不能继承许可确认或自动执行。
4. 查询原命令与 `/quality/http-fixture-executions/{invocation_id}`，核验完整 canonical
   input digest、原 selection、原 claim IDs、phase inventory 和所有 false authority。
5. 原执行仍 running 时，独立勾选、确认 `quality.http_fixture.cancel`；随后只查询原执行
   和原 control。请求已登记与已投递分开展示，投递不表示目标停止、清理或业务回滚。

新请求、恢复后待确认请求都会在确认前 GET 核对原 ID、业务字段、request key/hash、
状态。角色、完整来源 ACL、许可寿命、目标 preflight、worker fencing、派发事务仍由
后端权威检查；浏览器校验或按钮可点击不能授予权限。超时、换 scope、未知附加业务字段
或错误摘要在写入前拒绝。原协调字段保留在 canonical digest，不把它们当新的业务输入。

## 状态与恢复

sessionStorage 只保存账号/项目/计划/recipe 范围内的 ID、摘要、原环境命令 ID、attempt、
operation、timeout 和三个独立 request key/hash/command ID；不保存源码、recipe 原文、
环境库存、URL、凭据或归档。先固定 request key，再发请求；先持久化 ACK，才确认。
存储写入失败不继续派发，已有 scope/阶段不能被另一个请求覆盖。

丢失 ACK 后根据原 command ID 或 project/tool/request key **GET 恢复**，不重新 invoke、
不自动确认；恢复得到 waiting_confirmation 后需要新的用户勾选。失效、撤权、篡改及
读取错误隐藏受保护内容；重新核验、当前输入、scope 或证据更新时间变化使确认失效。
刷新查询时不展示旧 query cache 为新 scope 的准备结果。

点击提交时复制已核验的 exact input 与操作范围作为 Mutation variables。pending 会停用
敏感查询并改变 query key；Mutation 不再从会被清空的 grant/execution query data 中取
参数。实际写入仍从当前 session 元数据回读原 command ID，API/后端重验原输入、账号、
摘要和权限；固定点击输入不授予新的权威。输入 hash 计算完成后才回读 session 进行
同步 CAS，避免 hash 的异步等待把旧恢复元数据当作当前值。

v2 的绑定前状态保留 `intent_digest=null / phases=[] / target_observation_verified=false`。
v1 按原 definition 的完整 phase 顺序显示 not_dispatched、outcome_unknown 或 observed；
completed 必须已有全部 observed phase，但 result_status 可以 failed。任何状态均不批准
业务覆盖、Run、测试通过或 baseline restoration。命令与任务 GET 之间若恰好有终态变化，
最多三次只读重查同 ID，不创建替代任务或发送目标请求。

outcome_unknown、failed、cancelled 不显示“下一次操作”捷径。完整 observed 的 completed
setup 可以显式准备同 attempt 的 cleanup 表单，但仍需重新核验环境、单独授权和确认，
不会自动清理。completed cleanup 后的新 setup 使用新 attempt。原服务端归档不改写。
当前操作面板仍只保留原 session 恢复入口。2026-10-13 已另接项目知识页的
[项目级原命令发现](./http-fixture-operation-history.md)，可跨浏览器分页读取三类命令
及只读关联元数据，后续[原阶段核验](./http-fixture-original-observations.md)已可按原 ID 回读
完整持久阶段，不依赖 session。独立效果处置/恢复和 unknown 处理仍需交付，不把发现
ID、取消终态或历史观察当作许可、回滚或业务覆盖。

## 已验证与剩余

`tests/unit/http-fixture-operations.cjs` 使用生产 Python 领域/应用编译与明确 native inspector
port specimen 校验 TS metadata/UUID/hash；不是实际构建或部署。包含完整多源码父链、
限时 v2 许可、污染拒绝、两个 GET 的终态竞争、原 ACK 恢复、三个独立确认和取消不回滚。
真实 hook 在明确 React/TanStack/transport doubles 下执行事件；SSR 验证折叠、阶段分离、
未知效果和取消提示，不证明真实浏览器调度、可访问性或轻/深/移动视觉。

2026-10-13 增加 `tests/browser/http-fixture` 隔离组件契约：真实 Chromium、生产面板、
React Query、StrictMode、现有 CSS 与中英翻译，API 全部为明确传输夹具，外部 egress
阻断。该运行发现并修复 pending 停用查询后取消 Mutation 读取 undefined 的实际竞态。
另补三项 grant/execute/cancel 输入快照回归。浏览器检查原 ACK 只读恢复、独立确认、
双击/刷新不重复写、v2 无 target observation、v1 failed 不晋级 coverage、同 attempt
独立 cleanup、unknown 无重发捷径和撤权/污染后父级隐藏；保存轻色英文桌面与深/浅色
中文窄屏截图。它是生产组件真实调度验证，**不是正式路由 E2E、后端授权或 exweb gold**。

最终命令终态、原失败、测试数量和运行日志见[实施记录](./implementation-progress.md)。
Docker 当前停止，未重启依赖、运行开发 migration、请求外部模型、拉取目标镜像或执行
exweb。真实 PG 锁竞争/事务、Temporal 重启/取消、公共 canonical RPC/exweb、E2E/smoke、
独立 unknown 恢复、逐step/case/oracle到coverage/release、五用途、旧链切换、安全性能/
灾备/多语言 Provider 独立 gold 和完整 V1 门禁均仍必需，不能由契约数量替代。

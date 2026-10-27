# 固定审阅输入的执行计划准备

更新：2026-10-10。RunPlan 保存原用例、脚本、独立审阅与目标声明，避免执行端重新读取可变工作区。当前能力只到 `prepared`，不执行构建、网络请求、数据准备或测试，不授予业务覆盖和放行权。完整目标仍按 [P0-P6 交付要求](./delivery-and-evaluation.md)验收。

## 输入与来源

计划通过 quality_loop application ports 回读完整原脚本和审阅。保留原 context、scope、generation、coverage、mapping、全部选中 case、步骤、预期结果及强制义务；不从最新 QualityAssetPack 重新拼装。脚本修订、审阅修订和双方工件摘要必须完全一致，当前审阅必须完整且没有未解决缺口。

目标声明包含全部原画像已采集代码来源的 binding/source revision、构建产物名称与摘要、构建定义摘要、运行时及构建工具版本。不能遗漏一个代码仓库或改用当前分支 head。画像、来源清单和完整来源成员也保留原摘要，代码以外的原需求和测试来源继续参与权限及历史验证。

环境声明仅允许 local/test/staging 的 HTTP origin，不接受 URL 凭据、查询参数、fragment 或业务路径。每个原用例必须且只能有一项测试数据声明，包含原前置条件摘要、数据清单摘要及 setup/cleanup 描述。描述是数据，不是可执行 shell、SQL 或 JavaScript；当前接口不导入外部产物或读取任意文件路径。

2026-10-12 增加独立的[HTTP fixture 准备/清理模块](./http-fixture-lifecycle.md)：显式完整
manifest 可按原 data_manifest_hash 连接上述声明，准备与清理分阶段、仅使用原响应资源 ID。
该模块没有改写本计划或新增公开派发入口，仍需正式 PG journal、独立批准和完整执行接入。

`plan_digest` 固定全部输入和声明。字段变化后必须重新预览与确认，不能沿用旧摘要。完整计划超过 16 MiB 时拒绝，不截断用例、步骤或 oracle。

2026-10-11 增加 [HTTP 响应资源绑定](./http-response-bindings.md)的显式计划迁移：已审阅 proposal v2 只能选择 `nasus.run-plan.v2`，私有归档为 `nasus.run-plan-artifact.v2`；旧脚本与计划仍使用原 v1 语义和 hash。协议来自固定原脚本，不从新回复或运行结果推断。构建绑定、原命令编译和观察回放保留这个选择以及全部原 case/step/oracle；新的 capture 不是独立预期、fixture 授权或业务覆盖。

## 预览与保存

HTTP `POST /v1/projects/{project_id}/quality/run-plan-previews` 和 canonical `query.quality.run_plan_preview` 共用只读预览。返回保存请求、计划摘要、权限范围摘要、用例及义务数量和剩余门禁，不启动 Provider、构建或 Runner。Agent 使用旧查询回执时重新授权并回读，不把 metadata 回执当作正文或执行授权。

正式保存只通过 canonical `quality.run_plan.prepare`。执行账号必须是当前 qa_lead/project_admin/platform_admin，命令必须处于 running，并由同一账号确认完整原请求。确认时间须带时区，不能在未来，且有效期为 15 分钟。新保存前和提交事务内均检查；过期、无时间或错误账号在私有计划归档前拒绝。已提交命令的原计划重放不要求重新确认，也不重绑新输入或重新生成脚本。

私有 MinIO 保存完整原请求和计划；PG 的 `quality_run_plans` 保存不可变元数据与工件摘要。来源读取只复用操作内已核验的固定元数据快照，当前角色、来源 ACL、审阅头和上下文有效性仍重新检查。归档期间上游撤回或权限变化不能借缓存绕过提交门禁。

## 事务与历史

0101 明确固定 DDL，不从未来 ORM 自动生成旧 schema，不为历史 Run 伪造计划。表通过复合外键连接原 context、image/manifest、脚本/审阅，以及 0100 登记中的确切节点与 content hash；数据库拒绝 UPDATE/DELETE，非空历史阻止破坏性降级。

计划事实、审计及 Outbox 在同一项目锁和 PG 事务提交。归档完成后再次核验原输入、来源访问权和当前审阅头；迟到撤回、错误 ancestry 或较晚 Outbox 故障回滚数据库事实。MinIO 不参与 PG 事务，失败后未引用物理对象仍需后续受控 GC，不能声称存储已完全原子化。

HTTP `GET /v1/projects/{project_id}/quality/run-plans/{run_plan_id}` 从原 canonical command 恢复请求，先重新授权全部原来源并核验上游历史，再读取计划正文。读取检查完整内容摘要、原上下文与画像、全部用例/动作/oracle 和所选审阅；缺项或损坏拒绝，不借最新事实修补。响应使用 `private, no-store`。

后续撤回不改写原计划和原审阅。历史仍可在当前有权时回读，但 `inputs_current=false`；旧事件核验对应的原审阅前缀，不跟随新头。权限撤销后的历史正文同样拒绝。

## 原命令回执与共享视图

计划准备和预览的 ToolInvocation 包含目标地址、构建及测试数据声明，不能因账号属于项目而直接返回。专用 GET、同账号的幂等键查询、原命令重放、确认以及工具／审计列表，通过 RunPlan application port 重新验证原脚本、原审阅、双方工件摘要、原画像及全部来源；批量返回前再核验当前权限。未配置对应授权端口时拒绝，不降级为项目权限检查。历史审阅撤回不改写已保存内容，也不授予新保存或执行权。

会话创建、列表、详情、归档和搜索，以及 conversation／goal／swarm 事件重放只展示命令 ID、工具和通用生命周期摘要。原声明、结果和幂等恢复键不进入共享投影；新事件先脱敏再发布，旧 Outbox 在发送时脱敏，不修改数据库里的原事件。共享视图不提供来源访问许可，正文必须另走重新授权的专用读取。

## Portal 表单与恢复

生产知识路由的脚本独立审阅面板已接入 `RunPlanPanel`。只有完整且当前可用的原审阅才能准备新计划；用户点击后才读取全部原来源并展示表单，不自动选择环境、构建或测试数据。表单收集完整代码版本、构建和运行时声明、目标 HTTP origin、每个原用例的数据清单以及 setup／cleanup 说明，沿用 shared 主题与局部滚动，不增加执行入口。

领域模块校验完整来源分页、请求／计划摘要、原 context／scope／generation／mapping、全部 case／step／oracle 与归档内容；页面不把服务端标签或通过计数当作证明。预览、勾选确认、原 canonical 准备命令和确认分开进行；字段、审阅、来源或重新读取变化会清除确认。成功显示原计划、完整保留数量和剩余执行条件，计数仍为零。

发送写入前，sessionStorage 仅保存按账号、项目、脚本及审阅隔离的原请求键、请求摘要和可选命令 ID，不保存目标地址、测试数据正文、工件或密钥。创建或确认回执丢失时不重发 POST，只读查询原账号的确切命令，并校验原请求与全部输入。恢复到 waiting_confirmation 后必须重新勾选并显式确认；恢复到 completed 后回读原归档。成功核验后不继续显示旧失败提示。

受保护查询不自动重试或保留闲置正文缓存；来源撤权、错误 pin 或损坏归档会隐藏旧内容。未能核验原请求时不能创建替代命令；只有完整回读已保存计划后，用户才能显式开始另一份声明。上述恢复不启动 Provider、构建或 Runner，也不继承目标执行授权。

## 当前验证与执行边界

计划始终返回 `target_verification=declared_not_native_verified`、`execution_authorized=false`，automated/executed_on_target/passed 均为 0。脚本独立审阅接受不等于目标构建已核验，也不代表用例已实际执行。

纯测试覆盖完整输入与字节预算、错误修订/摘要/fixture、严格审阅布尔值、历史及权限重验和 DDD 边界。隔离 PG/私有 MinIO 专项覆盖 canonical 确认、历史撤回、FK/schema/不可变、过期确认、归档期间撤回及晚期事务故障；各批次是否已执行和终态见[实施记录](./implementation-progress.md)，测试定义不替代通过证据。

固定 exweb 专项核验原 commit/tree、126 个原 Git blob 和固定代码成员与计划来源一致。需求、用例、oracle 和模型 HTTP 是明确的协议 specimens，目标产物和环境也是声明；它不是维护者业务 gold、外部模型质量或已执行 exweb 的证明。

后续[原生构建](./native-target-build.md)已有 canonical 预留、生命周期、固定私有源码、实际离线 Maven 构建和完整 JAR/日志归档回读。0103 的[独立构建绑定](./run-plan-build-bindings.md)核验本计划的完整原代码范围及原始产物，另存追加式结果，不自动改变旧 prepared plan。该构建和绑定的实际验证范围分别记录，未核验的环境/fixture 或执行权不能从构建成功推导。

下一步必须交付环境/定位/fixture 核验、独立执行授权、canonical RunPlan 执行及逐 case/step/oracle 证据回流，并完成多语言构建范围验证。现有 `run.start` 仍读取旧自动化资产蓝图，尚未切换；五用途 ContextPack、完整项目失效 DAG、自动增量、治理终态原子链、安全性能与试点也仍属于原目标。Portal 已有计划声明、原生构建及完整来源构建关联表单，也提供独立取消与原命令只读恢复；它们没有消除环境、测试数据和真实目标执行门禁，不能称完整 P5 已完成。

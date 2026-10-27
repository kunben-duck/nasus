# 固定 HTTP fixture 定义登记

更新：2026-10-12。0110 补齐 P5 的正式输入登记：完整测试数据准备/清理定义可以由独立
确认的 canonical command 保存，后续执行授权能够引用确定的 record ID 和 hash。
登记不是执行许可，不调用 Runner、目标 HTTP、模型或原生构建。完整 P0-P6 目标不变。

## 固定输入与祖先

请求为 `project_id / run_plan_id / run_plan_artifact_hash / manifest`，manifest 是完整的
`nasus.http-fixture-manifest.v1`，不是调用者提交的运行结果。保留全部 case ID、原前置条件
摘要、setup/cleanup 描述、准备步骤、立即捕获的资源 ID、状态/业务断言及分组清理。
既有 128 KiB、400 步和 16 个资源限制仍有效；超过限制拒绝，不截断后登记。

application 通过原 RunPlan read port 重新核验全部脚本、审阅、上下文、来源与原归档。
`bind_run_plan_fixture` 要求完整定义的 hash、case、前置条件和描述与原计划声明一致。
修改 oracle 或清理范围必须形成另一个被明确保存的计划，不能改写旧声明。

PG `quality_http_fixture_recipes` 保存原命令、认证 actor、记录时间、原计划复合外键、
画像/来源清单 pins、case、data manifest/fixture/request/archive hash 和元数据。
旧 RunPlan 元数据没有 image/manifest hash；新登记从其不可变 FK 父记录取得，并与
application 回读的完整原计划核验，不给旧记录增加或补造字段。

完整请求和祖先存入私有 MinIO 的 `quality/http-fixture-recipes/<project hash>/<archive hash>.json`。
登记和历史读取要求 S3，不能静默回退到本地对象。历史会物理回读原字节、重新检查 hash、
namespace、完整定义与原 RunPlan。`recipe_bytes_verified=true` 只说明定义归档可核验，
不表示 fixture 已准备、清理或恢复业务基线。

## Canonical 与读取

正式写入口只有 `quality.http_fixture.register`，采用 ToolRuntime 的独立 `user_confirm`。
PG 原事务要求确切工具、输入、running 命令、相同确认账号、非未来的 15 分钟确认和
原会话项目。当前角色为 qa_lead/project_admin/platform_admin，全部来源访问权持续有效。
原命令重放恢复同一登记；不会再次写入归档或产生第二份事实。

登记、审计和 metadata-only Outbox 在同一个项目锁/PG 事务提交；晚期 Outbox 故障全部
回滚 PG 事实。S3 写入和 PG 不是分布式事务，未引用归档的 GC 仍属于剩余交付。
记录由数据库触发器禁止 update/delete；有历史时拒绝破坏性 downgrade。

只读入口：

```text
query.quality.http_fixture_recipe {project_id, record_id}
GET /v1/projects/{project_id}/quality/http-fixture-recipes/{record_id}
```

HTTP 返回完整归档，private/no-store，先检查当前 reviewer/source ACL，再读私有定义。
canonical query 和 Agent observation 只返回 ID/hash/状态元数据；Agent 再次使用旧回执时
重新授权并回读原定义。SSE 的命令 input/result 均脱敏，不广播准备正文、目标资源或预期值。
登记事实事件只含 project/record/run-plan 的不透明 ID 和状态，不含 case ID 或定义 hash。
缺失 resource authorizer、归档损坏、外部范围或撤权都拒绝，不修补历史。

## Portal 输入与恢复

原 RunPlan 面板新增默认折叠的独立测试数据定义入口。展开后才显示完整 JSON 输入，
不从执行响应、代码或模型补造准备步骤及 oracle；先核验原 case、前置条件、setup/cleanup
声明和完整 manifest hash。共享 HTTP action 校验保留请求顺序、立即 capture、状态断言、
自有资源清理、禁凭据/外部 origin、完整步数和字节限额。重复 JSON keys 和不安全数值拒绝。

核验成功后才展示独立确认；编辑原输入即使只是空白也使预览及确认失效。新增登记只走
canonical ToolRuntime，不增加直接 HTTP 写入口。原 command input、UUIDv5 record、全部
parents、完整 archive 和严格类型 metadata 都重新验证，不相信响应自报的执行或通过计数。

sessionStorage 仅保存 actor/project/plan/hash、request key/hash 与原 command ID，不保存
定义、资源或正文。失联/刷新后仅 GET 原命令与私有归档，不自动重发登记或确认。恢复到
waiting_confirmation 必须重新勾选；损坏或撤权隐藏父链，暂时查不到结果不会创建新命令。
历史记录仍需当前来源权限，但历史只读不假装 inputs_current 或授权目标执行。

面板沿用 shared token、细边框和圆角，输入/归档保持有界无可见滚动条滚动体验；中文
文案强调只登记定义、不执行准备/清理。浏览器协议 specimen 与真实 PG/MinIO 登记专项
分开取证，均不是 exweb 作者的业务批准或目标执行，终态见实施记录。

## 权威与剩余范围

所有记录保留：

```text
fixtures_verified=false
execution_authorized=false
canonical_execution_committed=false
business_coverage_verified=false
baseline_restored=false
automated_count=executed_on_target_count=passed_count=0
```

独立登记确认不等于允许对目标准备数据，更不是业务 oracle 批准。0108/0109 私有
journal/worker 仍没有挂入 production 执行链。后续必须将此登记连接到独立执行/清理授权、
真实运行时 locator/fixture 预检、canonical/Temporal dispatch、取消、未知效果恢复和
逐 case/step/oracle 到覆盖/放行的反馈。完整 RunPlan 当前用途门禁、
身份/租户及其他适配、五用途 ContextPack、旧链切换、独立 gold 和性能/安全验收未完成。

本轮纯测试使用明确的协议 specimen；PG/MinIO 专项建立完整原始 canonical 父链，但
仍不是 exweb 维护者的需求/业务批准，也不执行 exweb 目标。固定 exweb 原生 fixture
与 readonly 重放的已有事实保持不变，不能将登记专项改称真实业务覆盖。终态见
[实施记录](./implementation-progress.md)。

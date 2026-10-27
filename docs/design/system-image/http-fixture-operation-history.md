# 项目级原测试数据命令发现

更新：2026-10-13。该入口补齐跨浏览器的原命令发现，不依赖当前操作的 sessionStorage。
它只提供重新授权的元数据，不是独立 unknown 处理、重新执行、目标运行或完整 P5 验收。

## 来源与查询边界

- 发现原 `quality.http_fixture.authorize / execute / cancel` 三类 ToolInvocation。
  不只查询 preparation/intent 表：等待确认、准备失败及绑定前命令也必须可发现。
- 按 project 和原输入连接完整原 recipe；execute 经原 grant，cancel 经原 execute/grant。
  历史读取使用已归档环境与配方，不调用 require_live、不续期、不启动目标或 Worker。
- 当前角色与其他 fixture 入口一致：project_admin/platform_admin。不是仅查当前 actor
  或当前浏览器创建的命令；读取他人的历史也不取得其确认、许可或执行权。
- SQL 对原 manifest 的全部来源 binding 做当前可见性过滤，再计算 total 和分页。
  计数、page、look-ahead 来自同一 SQL statement；缺原父链或空来源范围时拒绝声明
  完整库存，不将损坏历史跳过后返回零。无权来源不参与计数或游标。
- 默认每页3、上限5，按原命令 ID 排序；这不是时间排序。应用层重新读取每个返回项
  和 look-ahead 的完整配方/许可 ancestry，并在返回前重新检查当前 source scope。
  total 是可见、持久化命令库存数量，不声称页外每份归档已经逐一校验。

结果只含 project/command/stage/status、完整原请求摘要、recipe/RunPlan/case/attempt/op
及原 execute/grant IDs/hash。没有来源正文、运行地址、密钥、幂等恢复键或工件 URL。
`observation=original_command_metadata_not_target_observation`，四项 execution/canonical
commit/business coverage/baseline restoration authority 始终为 false。
completed、failed 或 cancelled 仅是原命令状态，不能推出请求效果已知或通过。

## API、Tool 与回执

```text
GET /v1/projects/{project_id}/quality/http-fixture-operations?after_id=&limit=3
GET /v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}
query.quality.http_fixture_operations
query.quality.http_fixture_operation
```

HTTP 成功和授权/完整性/不可用错误均为 private,no-store。PG 读取失败返回脱敏503，
原 ancestry 损坏返回502，权限/权限变化/缺记录仍遵循403/409/404，不返回旧内容或空库存。
输入分页限制由请求验证处理。

两项 Tool 共用 application service、原 ToolHandler/RBAC 和 receipt access。canonical
查询会保存自己的控制回执，但不改写原 fixture 事实或派发请求。回执是需要重新查询的
瞬时观察，不是冻结项目列表；新命令、状态/confirmation digest 或 ACL 改变会要求重新
检查，不能拿旧页隐式确认命令。共享会话/SSE 仍只广播通用状态，input/result 隐藏。

## Portal

Knowledge 增加默认折叠的“查找历史测试数据操作”。点击才查询，支持分页、重新核验和
明确选择一条原命令进行只读元数据展开。查询 key 包含 project/actor，retry=false，
gcTime=0；读取/翻页中隐藏旧明细，权限、状态、scope/count/cursor 或完整性不一致时
隐藏列表与明细，要求用户重新核验。账号退出和项目切换不能显示旧项目结果。

沿用既有主题、review queue/scope 样式和中英文案，长 ID 可换行。不保存新的本地恢复
键，也没有新建、确认、取消、重新执行或“未知效果重发”的快捷按钮。
原 session 操作面板继续负责已保存 attempt 的独立确认与取消；从这里发现 ID 后，
现可另行[核验原持久阶段](./http-fixture-original-observations.md)，不依赖本地恢复键。
它仍不处理 unknown 效果、补写结果或执行；完整独立处置/恢复继续待交付。

## 验证范围

- `test_http_fixture_history.py`：生产 grant/history 用例与明确 ports specimen，完整阶段、
  状态、原 ancestry、look-ahead、ACL、false authority、SQL编译/故障及损坏空页拒绝。
- `test_http_fixture_history_routes.py`：真实 FastAPI router 与生产 application、port doubles；
  GET/405、分页请求、脱敏403/409/404/502/503及no-store；不导入 app.main 或启动数据库。
- `tests/unit/http-fixture-history.cjs`：生产 Python编译出的协议 specimen 与 TS
  validator/API/hook；严格21字段、分页/来源变化、退出/切换/刷新隐藏、只读GET。
- `test_project_history_pg_discovers_pending_and_cancelled_originals_without_effects`：已补在
  `test_http_fixture_execution_api.py`，准备真实隔离PG/MinIO、canonical未确认/取消及
  SQL全来源过滤验证。workflow/build/HTTP transports仍为明确 doubles。
  Docker停止时不导入该文件或冒称已运行，当前只语法检查。

命令终态和失败日志见实施记录。新入口尚未有正式路由真实浏览器、最新实际PG/MinIO、
Temporal RPC/重启或原生exweb集成结果，不能由契约通过声明这些门禁绿色。

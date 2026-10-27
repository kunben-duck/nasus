# 跨浏览器的原测试数据阶段核验

更新：2026-10-13。接在[项目操作历史](./http-fixture-operation-history.md)之后，按原项目命令
发现并重新授权读取完整持久阶段，不需要当前浏览器的恢复键。这是只读历史核验，
不是 unknown 效果裁决、补写结果、重新执行或完整 P5 验收。

## 原始来源与状态

```text
GET /v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}/observation
query.quality.http_fixture_operation_observation
```

应用层先核验当前 project_admin/platform_admin 及来源权限、原命令、原配方、完整
RunPlan/脚本/ContextPack ancestry。execute 使用原 grant 和已归档的原生环境；cancel
只指向原 execute，不把取消确认转成执行许可。历史环境与过期 grant 只做回读，不
调用 require_live、目标探测、lease、Runner、Temporal start 或新 attempt。

已确认执行由原 jobs.read port 回读 preparation/intent 与全部阶段。阶段库存来自
完整原 manifest，包含 cleanup 的每个 capture binding，claim ID 从固定 project /
attempt / case / phase 推导。响应只含选定命令及原 execute 元数据、expected phase
pins、原持久 job 状态和摘要；不含输入正文、幂等键、目标地址、密钥或对象 URL。
前端核对严格字段、原请求和来源 fingerprint、完整阶段库存与 claim、结果摘要；
完整私有祖先归档仍由后端 ports 验证，不宣称客户端下载重放了全部档案。

| state | 含义 |
| --- | --- |
| not_execution | 原 grant 命令，不是目标执行 |
| not_confirmed | 原 execute 仍 pending / waiting_confirmation / waiting_approval；无 journal、无阶段 pins |
| preparing / preparation_failed / preparation_cancelled | v2 preparation 回执，intent=null、phases=[]、target_observation_verified=false |
| not_dispatched | v1 原完整阶段均无持久派发 |
| outcome_unknown | 任一原派发没有可核验的持久输出；取消、失败不能消除 unknown |
| partially_observed | 部分阶段已有原输出，其他阶段尚未派发 |
| observed | 原完整阶段均有输出；保留 passed/failed/error/timed_out，不表示业务通过 |

failed/cancelled 命令若没有原确认或可核验 journal，不伪造未派发回执，读取失败。
completed 也必须有全部 observed 阶段，不能仅凭命令终态声明已观察。四项
execution_authorized / canonical_execution_committed / business_coverage_verified /
baseline_restored 始终 false，准备回执不能升级成目标观察。

读取最后重新查询选定命令和原 execute，再检查当前 ACL；期间 confirmation/request
digest 或状态变化返回 private,no-store 409，要求显式检查同一 ID。所有成功和错误
沿用私有缓存策略；完整性错误不是空成功。canonical query 使用相同服务，控制回执
每次展开重新核验；阶段改变后旧回执返回409。共享会话/SSE 保持通用状态，隐藏
input/result，不向其他会话传播历史正文或原许可。

## Portal

生产 Knowledge 页的折叠历史队列在显式选择元数据后，另点“查看原操作的阶段记录”。
查询按 project/actor/original command/request/status/source scope 隔离，retry=false、
gcTime=0、no-store、AbortSignal；读取中隐藏旧元数据和观察。权限、状态或协议错误
隐藏队列与明细，要求重载历史；刷新或换浏览器仍可按服务器库存重新发现原 ID。
没有确认、取消、重发或新操作快捷按钮，没有 sessionStorage 写入。

窄屏长 ID/阶段分行；局部按钮沿用 shared tokens、细边框和主题，未改全局按钮或图标。
unknown 明确说明不可重发、取消不代表回滚，已观察的失败不提高 coverage。

## 验证与剩余范围

domain/application tests 覆盖完整阶段、cleanup 多资源、unknown 优先、失败和取消、
prebinding、篡改/额外字段/authority 强制类型、原命令竞争、ACL 撤销与 canonical
回执。真实 FastAPI router 使用明确 ports specimen，不导入 app.main。

新增 fresh-interpreter 入口检查同时修复 tool_handlers 包的 eager registry 循环导入：
辅助查询不加载全部 context，旧具名与星号导出保持兼容，不靠测试导入顺序掩盖问题。

TS/API/hooks 使用生产 Python DTO 编译结果及明确 doubles；Chromium 真挂载生产
HistoryPanel、React Query、StrictMode、主题及翻译，覆盖桌面英文、390中文深/浅色、
刷新、读取时隐藏、取消仍 unknown、撤权/篡改隐藏、无写入/外部 egress/未知 API。
这不是正式项目路由、真实认证/ACL、PG/MinIO/Temporal 或 exweb gold 验证。

真实隔离 PG/MinIO 的原历史集成定义已补 pending 与 cancel→原阶段查询；当前
Docker 停止，只语法检查，未导入/采集/运行。具体命令证据见[实施记录](./implementation-progress.md)。
独立 unknown 人工处置/效果恢复、真实执行证据逐 case/step/oracle 到 coverage/release、
五用途/旧链切换、完整 P0-P6 及 V1 门禁继续待交付，不由这个查询缩小原目标。

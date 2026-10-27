# HTTP 多步骤响应绑定

更新：2026-10-11。P5 执行器增量：同一固定任务从原始 HTTP 响应获取资源 ID，继续读取和关闭该资源。它不替代完整系统画像、独立 oracle、已审阅脚本、执行授权或正式用例覆盖。

## 显式版本与依赖方向

`AutomationRunnerCommand.http_protocol=nasus.runner-http-execution.v2` 显式选择新协议；默认仍为 v1。Python 的原请求编码、Node 的原字节 hash、原 v1/browser receipt 和响应工件结构不变。不能根据不可信结果自动升级协议，browser 命令也不能选择 HTTP v2。

新增 `capture_json` 动作仅包含 `request_id`、RFC 6901 `pointer`、`binding_id` 和可选原 `source_step_indices`。响应绑定是资源定位事实，步骤类别为 action，不是 assertion，不增加已观察/通过断言、自动化覆盖或执行授权。

领域层提供纯步骤/响应校验，application port 明确版本；基础设施实现 HTTP、严格原字节回读和私有工件核验。没有领域 ORM/HTTP/MinIO 依赖，没有新增绕过 `ToolInvocationRuntime` 的 UI 写入端点。Runner 的内部 `/v1/jobs` 继续要求服务认证。

## 定位与拒绝规则

- 所有动作在第一条网络请求前完整校验，至多 100 步、32 个唯一 binding；不得前向引用、重复声明或重赋值。capture 只能引用之前的 request。
- 只从原 2xx 响应提取字符串 ID，长度 1-128，字符限定 ASCII 字母、数字、下划线和连字符。缺失、null、boolean、number、对象/数组、路径逃逸、斜线、反斜线、百分号、查询/fragment 和其他字符拒绝。
- 响应必须完整有效 UTF-8 和严格 JSON；重复 key、深度/数值越界及非法 pointer 拒绝。支持根值、转义字段和合法数组索引；不以缺失值代替 null，不强制转换类型。
- 仅完整路径段可以使用 `{{binding_id}}`，例如 `/sessions/{{session}}/close`。不支持部分段、动态 origin/query/header/body/oracle；这些字段始终保持原显式字符串。静态 query 可以保留，动态 query 在派发前拒绝。
- 同一原目标 origin、host 白名单、固定 DNS、无代理/重定向/自动重试、响应预算和截止时间规则不变。绑定不能提供身份凭据、模型调用或新的目标权限。
- capture 失败后该步骤 interrupted、后续 not_executed；原响应保留，但不补造 binding。独立断言失败后保留已完成的绑定及响应，不执行后续请求。超时/断开仍不自动重复可能已有副作用的操作。

## 回执与物理重验

v2 receipt 增加有序 `bindings`：`binding_id / step_index / request_id / pointer / response_hash / value / value_hash`。value hash 为该有界 ASCII 字符串的紧凑 JSON UTF-8 SHA256，不由调用方声明成为可信事实。

v2 请求观察保留原八字段，并增加 `declared_input_hash`、解析后的 `path` 和首次出现顺序去重的 `binding_ids`。`declared_input_hash` 固定原 method/path/headers_json/body_json；`input_hash` 固定仅替换资源路径段后的四项字符串。`nasus.http-response.v2` 与 body 原字节、metadata 原字节和完整 manifest 一起归档。

API 先核验原命令选定版本、完整步骤、绑定顺序/端点/源响应/hash、实际路径和两种输入摘要；随后回读全部响应字节，重新严格解析并提取每个 capture 值，核对原值/hash。即使伪造者同步改了后续路径、metadata 和所有派生 hash，也不能把不是原响应中的 ID 验证为成功。已观察的四类独立 oracle 继续从原响应重算。

原响应和绑定值只在受控结果/私有工件内保存，不进入通用 timeline、metrics 或服务日志。私有存储的历史回读不是新的执行，也不能恢复已撤回的权限。

## 验证范围

Runner 单元测试使用真实本地 HTTP 服务生成随机 session ID；覆盖同任务创建/读取/关闭、失败后停止、非法 ID、坏 UTF-8/重复 JSON、根/转义 pointer、前向引用/重赋值/预算及 v1 兼容。纯领域 specimens 另覆盖完整自洽伪造的物理回读拒绝；这些不是业务 gold。

原生联测通过实际认证的 Node Runner `/v1/jobs` 和私有 MinIO，分别验证成功、关闭后负向状态、截止时间及认证/版本拒绝。归档完整原 command/result，新存储实例回读后从原命令重新核验；不重新派发。测试所用 PostgreSQL/bucket 均为 disposable，未迁移开发库。

固定 exweb 的真实构建/三源关联和运行验证见[原生验证](./exweb-native-runtime-validation.md)。原生探针使用实际固定 JAR 和 operator-only Docker transport；同任务 ID 无外部接力，独立 title/tenant/user/status 预期仍为开发检查，不从 create 响应生成业务答案。

具体加载批终态、失败和日志见[实施记录](./implementation-progress.md)，范围重叠不相加为项目用例总量。

## 显式脚本与计划迁移

Portal 的脚本预算表单默认 v1，用户明确选择响应绑定后才在请求中增加 `http_protocol=nasus.runner-http-execution.v2`。新 grammar 纳入完整模型消息摘要和预算预览；协议改变清除前端确认，后端拒绝沿用旧预览。未选择新协议的请求不增加 null/default 字段，原消息、请求、工件及 v1 hash 保持原义。

v2 输出保存为 `nasus.automation-script-proposal.v2` 并显式固定 HTTP 协议。原生回复及结果容器仍是原有 v1 envelope，它们只是容纳确切请求和版本化提议，不改写原 DSL 含义。保存与历史读取都按原请求重验模型输出；不能根据回复中的版本自行升级。v1/browser 草稿仍拒绝 capture，v1 HTTP command 在发送前拒绝新绑定动作。

每项 capture 保留原 `source_step_indices`，必须和其他动作一样逐项独立审阅，不能绑定为 oracle。所有原用例、步骤、断言、预期文本及摘要继续完整保留；协议或 binding 变化不能沿用旧 action/review pin。审阅 envelope/policy 没有新的权限含义，保持现有 v1 的追加式规则。

已审阅 v2 提议只能准备 `nasus.run-plan.v2`，归档使用 `nasus.run-plan-artifact.v2`；旧提议只能使用旧计划政策。计划编译、历史回读、构建绑定、观察命令和私有观察回放均核验对应版本，禁止显式降级或重哈希后重新解释。Runner command 从原计划派生协议、全部原动作及 case/step/oracle pin，不重新读取可变资产。PG 现有 JSON 工件与追加式表可保存这些显式版本，不需要迁移开发数据库。

协议联测的 Node 目标是独立本地 HTTP fixture，预期结果来自原用例而不是提取的 ID；不把刻意失败的 fixture 断言改成成功。固定 exweb 源码的计划准备与真实 exweb JAR 的开发探针分开记录，不能跨批拼成正式执行或业务覆盖证据。

Portal 读取新草稿时复用严格 JSON 解析，不让 `JSON.parse` 的重复键覆盖变成有效动作。v2 的 headers/body/JSON oracle 校验与执行端保持相同的 64 层容器、256 字符数值和安全整数范围；原参数文本保留，不用 JavaScript 舍入后的数值改写 oracle。v1/v2 原生回复中的重复解码键同样拒绝，即使 raw output、response 与 archive hash 全部重新计算也不能通过。健康 JSON 读取的原默认契约不变，严格 HTTP 限制只由明确的调用方选择。

## 仍需交付

独立环境/fixture/locator 核验、执行授权、PG owner/lease、取消/恢复、真实逐用例覆盖到放行和旧链切换仍未全部贯通。回执的 `target_build_verified`、`business_coverage_verified` 保持 false；开发 probe 不创造 canonical 执行事实。完整 P0-P6、五用途 ContextPack、增量/overlay/merge、独立 gold、多语言/Provider 生命周期、安全/恢复/容量/性能/试点及 V1 绿色门禁保留为原验收要求。

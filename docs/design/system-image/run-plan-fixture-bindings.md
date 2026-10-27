# Fixture 捕获值与业务资源绑定

更新：2026-10-13。已交付完整捕获输入、私有原生 HTTP v3 协议及公共 v3 草稿／
独立审阅／RunPlan 编译契约，并接入主业务 Worker 的完整原始 setup handoff。
新协议的 scope/work/archive 已有真实 PG／MinIO 终态重放证据；实际 owned
exweb／Temporal 全链专项仍在核验，不据此宣称完整 P5、真实 exweb
业务覆盖、正式执行提交或 release authority 已完成。

## 来源固定的捕获输入

`RunPlanCaseInputApplicationService` 从原 canonical setup 历史读取所有原用例的
完整捕获集合，不接收调用者填写的资源值或 verified 标志。`CaseFixtureCaptures`
固定原 case scope、RunPlan、setup command/history、fixture attempt/manifest、目标
产物、environment/inventory、operator policy 和 setup 原请求/结果摘要。
每项 `FixtureResourceCapture` 保留原 request、step、JSON pointer、response hash、
资源值及其 hash；类型不可变，资源值不进入 repr。

完整集合必须保持原用例顺序和数量。遗漏、重排、跨用例、错误版本、错误原命令、
错误 capture/source hash 或额外成功标志都会拒绝。`require_current` 从原历史重新
构造并比较整个 prepared input，不能只相信调用者重新计算的 capsule digest。
这层是已物理核验读端口的内部投影，capsule/hash 本身不是证据签名或执行授权。

旧 v1/v2 脚本不消费这些值，不能通过替换旧路径、缩短分母或重算旧摘要伪装为
已经绑定。新公共入口必须显式选择 v3，生成新的独立草稿、审阅和 RunPlan；
主执行链不能只因 proposal 的版本或声明，就把它当作已经取得原 setup 证据。

## 公共 v3 草稿与计划

`ScriptExecutionSelection.http_protocol` 显式支持 v3，旧请求不添加空字段。原
automation prepared input、用例和 oracle 不改变；选择协议会改变原生模型预算
确认摘要，归档请求与 proposal 必须保持同一版本，LLMCall 的 prompt version 为 v3。
输出 proposal 使用 `nasus.automation-script-proposal.v3`，不修改原 result v1 envelope。

HTTP 草稿可以显式声明 `use_fixture_binding(binding_id, source_step_indices)`，不带
资源值、request ID 或 assertion。最多 16 个不同 import；先声明后使用，只允许
完整 path segment，并与同 job 的 capture 保持单赋值。缺失来源步骤、重复导入、
forward/query/partial binding、导入作为 oracle 或修改预期均拒绝。所有原用例、
步骤及每条独立 oracle 必须完整保留；生成阶段只声明需求，不证明 recipe 或 setup
存在，不能根据模型声明制造 capture authority。

独立脚本审阅保留 v1 policy：逐项固定完整 action digest、case/index 和每条原 oracle，
因此 import 也必须单独作出决定，不能漏审、复用旧 action hash 或升级成执行许可。
完整审阅后才能编译 `nasus.run-plan.v3` 和 `nasus.run-plan-artifact.v3`；旧 v1/v2 policy
不能承接新脚本。固定 source／target／environment／完整 fixture 声明、locator 的
原 request action indices 及 build binding 继续保留。PG 使用原追加式 payload 表，
没有为已有工件回填或重算摘要。

Portal 增加明确的 v3 选项和中文说明，协议切换清除旧预览／确认；新 archive、
RunPlan 和 build binding 的版本及摘要由共享验证器核验，默认仍保持旧 v1 选择。
v3 的业务 command 不能仅从 plan template 派发：普通 observation command compiler
仍明确拒绝。主业务 Worker 必须消费下述 producer 返回的完整原始 handoff，
在获取 lease／claim／调用 Runner 之前物理核验所有来源；版本声明本身不能派发。

## 主业务 Worker 的原始 handoff

`RunPlanCaseFixtureApplicationService.read_native` 与旧 `read` 使用相同 ancestry、
完整 setup／cleanup slots、当前访问权限和物理响应校验，返回独立不可变类型
`OriginalCaseFixtureWire`。原九字段 proof 不添加原文字节或空字段，新类型另携带
确切 request/result bytes，并在构造时核验原 hash。历史模式可读取后来已经清理的
原 setup，但不能据此开始新派发。

显式 v3 的 input producer 为所有原用例生成 `PreparedFixtureBoundCaseInputs`。
完整 capsule 使用原 base scope digest；独立 `FixtureBoundRunPlanCaseScope` 再按原
用例顺序固定 capture 和整个 fixture input 的 digest，避免 scope/input 循环摘要。
current guard 重读并比较全部字节、捕获和 pins；历史恢复同时核验 base scope 与
新 scope，不能丢掉新协议字段退化为旧 scope。客户端没有填写资源值的入口。

新 work schema 为 `nasus.run-plan-case-work.v2`，job digest 同时绑定原 template
和完整 fixture input digest。PG 仅保存原 scope、完整 roster 和元数据 pins，原
setup 字节只进入私有 `nasus.run-plan-case-native-archive.v2`。物理回放产生显式
v2 observation/state，完整保留原 action、step、oracle 和用例分母。Portal 按同一
新摘要核验历史，不能把换字节、换 capture 或省略 pin 的自洽结果当作原输出。

这些版本只扩展新 v3 输入。旧 scope/work/native archive/observation/state 的字段
和摘要不改变，不为已有历史补造 capture。实际配置的 `ConfiguredRunPlanCaseWorker`
在 execute/read 两个边界都传递完整 `fixture_inputs`，不能只让直接组装核心
worker 的测试消费它。旧输入不增加空参数，历史 read 不初始化目标执行器。
0120 canonical lifecycle 与 Temporal adapter 经同一个 application 入口消费新
producer；此次接线不等于真实 Temporal
或 owned exweb 全链已验收，原确认、实时 ACL、owner/epoch 和 unknown 不重发规则
继续独立成立。

## 私有 HTTP v3 协议

新 `FixtureBoundHttpCommand` 是独立类型；原 `AutomationRunnerCommand` 的
归档字段和 v1/v2 wire 不增加 `fixture_input: null`，不改写历史 command hash。

`nasus.runner-http-execution.v3` 要求 `fixture_input`：

- `schema=nasus.runner-http-fixture-input.v1`；
- 完整 `capture_set` 和 `capture_set_digest`；
- 原 setup request/result 的 canonical base64 字节。

业务 metadata 固定原 case/plan、case scope digest 和 capture digest。source 必须是
同项目、同 case、同 origin、同原 fixture scope 的成功 v2 setup，job ID 按原 scope
和 setup phase 推导；不能递归导入另一个 v3 输入。Python 和 Node 分别重新核验
完整 setup steps/requests/captures、原响应及 metadata 字节、所有 setup 断言。
源 setup 沿用原 recipe 的结构约束：捕获只能来自 POST 且紧随创建请求，每个
setup 请求都必须具有状态断言，不接受可重算摘要但原断言与实际响应矛盾的成功声明。
改变值、receipt 和它们的摘要但未改变原响应，仍会被物理核验拒绝。

新脚本动作 `use_fixture_binding(binding_id)` 是非断言 action。它必须显式出现在
使用前，绑定只能来自该用例的原捕获集合，不能重复声明或覆盖本次 capture。
只允许 `{{binding_id}}` 占据整个 URL path segment；query、部分 segment、header、
body 和 expected-result 不插值，资源 ID 仅接受有界 ASCII 标识。该动作不是业务
oracle，也不能引入新的执行权限。公共新脚本独立审阅和 RunPlan 编译已要求完整
保留原 action/source-step/oracle 映射；实际执行仍必须消费原 setup 而非自报声明。

回执新增原 `fixture_input_hash`、`fixture_capture_digest`、完整已观察的
`fixture_bindings`；每个请求同时保留 declared/resolved input hash 和实际 path。
Python 回读核对每个 import step、binding/value hash 及所有业务原响应/断言，
不能只以 Runner status 或后补描述作为证明。business/target authority 保持 false。

每份原 setup request/result 限 256 KiB；私有 job wire 仍限 512 KiB，CLI envelope
仍限 1 MiB。超限整包拒绝，不截断原响应、步骤或捕获集合；更大证据的 content-
addressed delivery、容量与性能需要另行设计，不能通过扩大上限绕过门禁。

## 执行边界

公共 `/v1/jobs` 即使持有 service token 也拒绝 v3 fixture 导入。它不能选择私有
owned-target transport、Docker resource 或替代业务授权。私有 Worker 在 dispatch
前核对捕获 environment/target/inventory/operator-policy 与当前 registry；CLI 再次
核对相同 pins，并保留完整 owned cohort/artifact fence。

这个协议只是资源操作数和原生观察能力。它不替代 ToolInvocationRuntime、独立
execution confirmation、实时来源 ACL、cleanup 状态、PG owner/epoch、Temporal
取消或未知结果规则。完整生产入口必须从原 setup 读端口取得字节、重新构造全部
捕获输入，并把它接入每次 dispatch/commit 的 current guard 和历史重放。

## 验证与剩余工作

Node 新测试包含实际本地 HTTP setup 与业务请求、动态生成资源 ID、原请求不重发、
失败断言与后续请求停止、expected-result 不插值和自洽伪造拒绝。Python 跨语言
测试调用实际 Node executor，但 business transport 与 setup 历史为明确协议替身，
同时经过真实物理响应 verifier；不当作 PG、目标 Docker 或 exweb gold。
公共 endpoint 拒绝和私有 target epoch 拒绝另有专项。

当前终态和测试选择集重叠关系见[实施记录](./implementation-progress.md)。仍需交付：
主业务 handoff 和新持久协议的实际全链核验、公共 v3 浏览器及实际
exweb/PG/MinIO/Temporal 执行链路、
独立 unknown 恢复、正式 coverage/release、五用途及旧链切换。完整 P0-P6 范围不变。

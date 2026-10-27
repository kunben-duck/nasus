# Runner 执行观察与原输入关联

更新：2026-10-11。这是 P5 真实运行证据的生产增量，不是完整 RunPlan、业务覆盖或五用途 ContextPack 的完成证明。[完整开发验收](./delivery-and-evaluation.md)的 P0-P6 范围保持不变。

## 实际执行回执

原浏览器 Runner 通过 HTTP 返回 status、timeline 和 artifacts；API 因此能接受与本次请求无关的 passed。现在浏览器执行的 `/v1/jobs` 返回 `nasus.runner-execution.v1`，API 通过纯领域规则验证：

- job、project、US 和执行状态与原命令完全一致。
- `request_hash` 来自实际发送的完整 UTF-8 字节。Python 只编码一次，Node 对收到的字节计算 hash；不是双方各自重序列化 JSON，也不接受调用者指定 hash。
- 每个原步骤恰好出现一次，保留 index、action、action/assertion 分类及 passed/failed/interrupted/not_executed。执行停止后的步骤全部未执行，不能补造后续成功。
- assertion/observed/passed/failed 数量根据逐步骤结果重新计算。goto/click/fill/press/wait_for 不是业务断言；仅导航的 passed 记录仍为零断言。
- `target_build_verified=false` 和 `business_coverage_verified=false`。回执不包含自授的用例批准、release readiness 或覆盖率。

只有实际 Playwright 操作完成才记录结果。截止时间到达后先封存回执，再等待截图/trace 清理；迟到回调不能改写结果或开始下一步骤。它不能撤销已经发送的当前页面操作，也不代表整个业务 Workflow 的取消或进程隔离已经完成。

空预期文本、缺少必须字段和不支持的 receipt protocol 在浏览器启动前拒绝。异常消息不回显私有 URL、请求或供应商异常正文。缺少回执、错 job/hash/count 或伪造 authority 的 HTTP 结果 fail closed，不接受 artifacts 或 passed。测试用 protocol_stub/unavailable 仍明确区分，不生成可信运行回执。

## HTTP 动作与原响应核验

脚本草稿已有 `kind=http` 的 request、assert_status、assert_json、assert_header 和 assert_body。Runner 现在真正执行这些动作，不把它们转成浏览器操作，也不从 timeline 推算断言结果。`AutomationRunnerCommand.kind=http` 明确选择 `nasus.runner-http-execution.v1`；省略 kind 仍走原浏览器协议，旧请求字节与 hash 不增加默认字段。

完整 HTTP 输入在第一条请求前校验。目标只能是无凭据、查询、fragment 或业务路径的 HTTP(S) origin，步骤路径不能换 origin。请求 ID 保留有界 Unicode 字母、数字、下划线或连字符；每个 ID 唯一，断言必须引用已声明的前置请求。请求头只允许 Accept 和 Content-Type，不接受脚本绑定 Authorization、Host 或路由凭据。GET/HEAD 的 body_json 必须为 null；其他方法按原 JSON 字符串的 UTF-8 字节发送，保留空白、字段顺序和转义，并由传输层设置准确的 Content-Length。

目标 host 必须符合 operator 的确切白名单，HTTP 不继承浏览器通配域名规则。未配置生产白名单时拒绝，开发默认仅允许 loopback。一次任务固定一次 DNS 解析，全部请求使用相同地址；metadata、link-local、mapped IPv6、未指定和 multicast 地址即使被列入白名单仍拒绝。请求不使用代理环境，不跟随重定向或自动重试，HTTPS 校验证书。解析与请求共用截止时间和取消信号，但这不是完整网络沙箱或目标部署版本证明。

每个完成的请求记录原 step index、request ID、method、四项原字符串的 input hash、实际状态码、完整响应字节数及 body/metadata hash。响应体原字节和包含实际 headers 的元数据分别保存为私有工件，另保存完整回执清单。API 检查整个工件 roster、严格 base64、精确原字节和元数据摘要，再从响应重新核验所有已观察断言；自洽但不符合原 oracle 的 passed 或 failed 均拒绝。headers 和 body 不进入通用时间线、metrics 或服务日志。

JSON 断言使用 RFC 6901 pointer 和保留类型的精确小数比较，不做字符串/数字/boolean 强制转换，不把舍入后相同的小数当成一致。重复 key、缺失字段、错误 pointer、非有限或不安全整数、超过 256 字符的数值、超过 64 层的容器都不通过。文本断言要求完整有效 UTF-8，不用替换字符补造匹配。

每任务最多 100 步、1–120 秒；单响应最多 1 MiB，全部完整响应最多 16 MiB。HTTP 500 或 302 是实际请求观察，不自动成为失败或成功的业务断言；是否满足预期由原 assert_status 等动作决定，302 不跳转。空响应仍保留零字节工件。响应不完整、超时或调用方断开时，活动步骤为 interrupted，后续为 not_executed；迟到响应不能改写封存结果。取消不能回滚已经到达目标的 POST 等操作，因此未知结果不自动重试。

HTTP 执行器和 API 防腐适配器已经接通，原生联测使用明确的本地 HTTP 夹具，并核验私有 MinIO 回读。旧 `RunOrchestrator` 仍选择浏览器命令，尚未把新的已审阅 RunPlan 派发到 HTTP 执行器；直接 adapter 调用不等于 canonical RunPlan 执行或 PG 正式用例证据。任务持久化、跨进程派发幂等、环境/fixture 核验、独立执行授权与真实 exweb 用例回流仍需交付，所有回执继续声明 target_build_verified/business_coverage_verified=false。

新增[显式 HTTP v2 响应绑定](./http-response-bindings.md)，同一任务从原 2xx 严格 JSON 提取有界资源 ID，仅用于后续完整路径段。capture 是 action，不算独立断言；模板/解析路径、原响应与 value 摘要均由 API 从原字节重验。v1 wire/receipt/工件不变，正式 script proposal/RunPlan v1 不自动接受新动作，需继续显式版本化迁移。

## 原用例与断言观察归档

`RunPlanObservationApplicationService` 从完整原 RunPlan 编译 HTTP job roster，保留原 case、脚本动作、source step indices、每条 row/oracle 摘要以及 context/scope/generation/mapping/script/review pins。所有选中用例必须满足 HTTP 执行器约束后才返回命令集合；较晚用例不合法时，不先返回可执行的前半批。`us_id` 在旧 Runner wire 中仅作为原 case 的路由标识，不把它冒充正式 US 身份。

批量观察只编译一次原计划，先检查全部实际 job 的确切命令、唯一身份、run attempt、超时、native mode 和完整 receipt，再从原响应字节核验各个结果。映射保留动作和 oracle 的 passed/failed/interrupted/not_executed。旧 v1 集合对没有提交结果的原用例保留 not_executed 的归档契约，但这不是派发前拒绝或目标副作用不存在的证明。不同 attempt 不可拼接，重新计算外层 hash 也不能掩盖改变的 oracle、job 或物理响应。

`RunPlanObservationArchiveApplicationService` 保存完整原计划、实际结果、所有物理工件、逐用例观察和重新计算的摘要。`nasus.run-plan-observation-archive.v1` 同时固定已保存 RunPlan 的 project/ID、原归档 hash 和 plan digest，不借同内容的另一条命令替换原计划。`SavedRunPlanObservationArchiveAccess` 通过现有 RunPlan application read port 回读确切父工件及全部来源权限；写入前、读取前和回读后再次核验，不缓存一次批准为永久访问许可。历史工件可以重放，但不恢复撤回的执行权。

存储适配器使用项目哈希前缀和内容寻址的私有 MinIO 对象，完整对象最多 32 MiB。超限整体拒绝，不截断原步骤、oracle 或响应；原字节 hash、严格 UTF-8、重复 JSON key 和非有限常量均核验。新实例读取后，应用层重新编译原 job、验证每个响应体、headers、manifest 和全部观察映射，不依赖旧进程的内存结果，也不调用 Runner、模型或自动重试。开发单元测试可显式使用私有存储 specimen，本轮原生存储联测使用真实 MinIO。

归档及其写后回读共用一次原计划的 `verified_read_session`，独立历史读取另开一次。该作用域只复用已有画像端口核验过的不可变来源／成员元数据，不保存计划读取结果或授权结论；原父工件仍完整回读，归档四次、独立回读两次原访问检查保持不变。当前账号、角色、来源 ACL 和审阅头不走缓存。正常返回或任意异常均关闭作用域，后续操作不能继承旧校验。作用域优化不代表延迟、吞吐或完整 P6 性能门禁通过。

这个归档是内部工作者可复用的观察接口，尚未成为公开 canonical 执行命令。0104 增加下节的 PG 观察登记、审计与 Outbox，不是 PG 授权执行事实。`execution_authorized`、`target_build_verified`、`business_coverage_verified`、`canonical_execution_committed` 保持 false；正式 automated/executed/passed 数量仍为零，实际通过/失败观察数量另列。生产 composition 接入独立登记和读取，不将该接口设为默认执行路径，不能用归档成功推导放行。

### 原观察的持久登记（0104）

`quality.run_plan.record_observations` 只接受确切 project、原已保存 RunPlan 的 ID/hash/digest、原 run_id、observation_artifact_hash 和 collection_digest，不接受任意对象 URL、内联结果、调用方提供的通过数量或执行权威。服务从配置的私有对象存储及项目内容寻址命名空间推导 ref，回读原计划与全部物理响应，再计算完整逐用例、动作/source step/oracle 清单。当前 reviewer、相同确认账号、完整原请求、15 分钟内的独立 canonical 确认必须同时满足，原 prepare/build 确认不能借用。

`quality_run_plan_observation_records` 通过复合 FK 固定原计划及 image/manifest/hash/digest，`quality_run_plan_case_observations` 固定全部原用例及有序动作/oracle 状态和摘要。一个 project/plan/run attempt 只登记一次；同 canonical command 的回读不改写原时间和内容，另一次命令不能覆盖已登记结果。完整主记录、所有成员、脱敏审计及 metadata-only Outbox 同一 PG 事务提交；失败全部回滚。两个表均追加式，downgrade 拒绝丢弃非空历史，普通读与事件核验不修补缺失事实。

授权 GET `/v1/projects/{project_id}/quality/run-plan-observations/{record_id}` 返回重新核验的原归档与登记。`query.quality.run_plan_observations` 只返回元数据、原始观察计数和零正式覆盖，不返回响应正文、私有地址或逐动作原文；Agent 使用回执时重新授权和回读。共享 Conversation/SSE 只发布脱敏命令生命周期，不能泄漏原请求或私有回执。来源撤权在读取前及回读后检查，历史不可变不等于永久可读。

登记只能证明原输入和响应观察已经持久记录，不证明实际环境运行了原 build、fixture 完成或经过独立执行批准。原 v1/v2 归档字节不改写，未知结果和没有提交结果继续分离。完整 canonical 派发、PG owner/lease、取消/恢复、环境/fixture 核验、真实覆盖回流、旧链切换及孤儿对象清理仍需交付；该增量不替代 P0-P6 退出条件。

### 事件重放的只读核验

SSE 重连不再直接相信 Outbox 的 JSON。`list_after` 在同一只读业务会话内核对严格字段类型、事件 ID/type/time、三个 stream ID、entity ID/type 和原正整数 sequence；整页核验成功后才返回，不先发送前半页。`Last-Event-ID` 只在所请求的 stream 内定位，其他 stream 的游标不能跳过当前历史。

`quality.run_plan.prepared`、`quality.run_plan.build_bound`、`quality.run_plan.observations_recorded` 同时回读完整原 PG 登记和已登记祖先，并核对原 canonical command 的 conversation/goal/time、metadata patch、查询键、append 类型和空附加 payload。缺失事实、错误登记或篡改事件整页拒绝；正常重放绝不调用 projector/backfill，不能把坏历史“修好”后当作原事实。

这里核验的是 PG 登记和事件归属，不在 SSE 中下载私有响应，也不替代来源 ACL、原物理字节、当前批准和真实环境核验。所有私有读取和 Agent 回执继续走原应用端口重新授权。其余领域的事件尚未统一到这种完整原事实验证；不能据此宣称全部 SSE、备份恢复、完整防篡改或性能门禁已完成。

### 回执缺失与结果未知

HTTP adapter 返回 error/timed_out 且没有 receipt 和任何物理工件时，`observe_http_attempt_batch` 只保存未经证实的原结果；它不创建 native observation，不把错误归为业务失败或未执行。确切 job、完整请求 hash、原 result hash、用例/步骤/oracle 与全部上游 pins 进入独立 `nasus.run-plan-unverified-attempt.v1`，各动作和 oracle 标为 unknown。`native_dispatch_verified=false` 表示没有可信目标派发证据，`retry_requires_new_explicit_attempt=true` 防止回读或恢复自动重发可能已有副作用的请求。

包含这类结果的完整归档使用新的 `nasus.run-plan-observation-archive.v2`。其集合分别列出已核验观察、outcome_unknown 和没有提交结果的 not_observed，不将后两者合并；同批已核验结果保留。没有未知结果的归档继续使用原 v1 结构和摘要，不改写旧工件。有 receipt 的真实超时仍走完整物理核验，保留 interrupted/not_executed；畸形 receipt、部分工件缺失、伪造 passed 或不同 job 一律拒绝，不能借 unknown 分支降级放过。

当前未知记录来自应用 adapter 的错误结果，不是持久派发预留或目标执行证明。PG owner/lease、原命令终态、取消和孤儿工件恢复仍需接入正式执行生命周期；未知结果归档不释放新的运行权限或已验证覆盖。

## 保存实际派发输入

Run 使用实际命令中的 TaskContext ID，不在模型/Runner 返回后重新选择 latest。私有 `runner-result.json` 保存原 `execution_request`、精确编码的 `execution_request_hash` 和已验证 receipt，三者可以重新核对；原请求包含步骤、目标 URL、超时和派发 metadata。对象内容继续使用 MinIO content hash，读取经既有私有工件授权，不向 SSE 暴露原文。

这里固定的是兼容 TaskContext ID 和实际 Runner 请求，不是已批准 ContextPack 的完整内容摘要、脚本修订或部署 build。请求中的 script/environment 引用只保留原输入，不因保存而获得批准。通用执行证据的 `case_ref=None`，不再使用 `case_set:current` 假称已关联到具体审阅用例。

旧批量 Run 保存和失败分析保存曾漏写执行步骤、US、目标、脚本、超时和重试字段，现在共用完整 `_assign_run`。没有倒推修复已经丢失的历史，也不从最新资产猜测原输入。

默认时间线只描述 Runner 返回及归档，不再补写“由已批准用例生成自动化”或暗示已经完成业务验证。原外部 timeline/history 不被重写，不能用展示文案代替独立批准或目标断言证据。

## Run 与证据的单次 PG 提交

`execute_automation` 先验证 receipt、归档所有物理工件，再通过 `QualityRunWorkspacePort.commit_run_execution` 一次提交完整 Run 和证据。两种 workspace 共用 repository 同一 PG 事务：

1. 校验 project/run/US、完整 storage refs、非空且唯一的 evidence IDs。
2. 新 Run 和全部证据同时保存，不批量重写同项目的其他运行或证据。
3. 相同 ID 的完全相同结果可重放；改变步骤/断言、证据 hash 或项目则拒绝，不能借提交入口修补孤立旧证据。
4. 即使 Run 已 flush，较晚 evidence 插入失败也回滚整个事务。兼容内存投影仅在 commit 成功后更新。

这一事务只覆盖 Run 与 evidence 元数据。MinIO 与 PG 没有分布式事务；PG 失败后已上传的私有未引用对象仍存在，尚需受控 orphan GC/恢复。旧独立 save_run_detail、materialize_evidence 和 failure/healing 等兼容入口仍保留，不能以新提交入口的拒绝改写声称所有历史事实已 append-only。canonical ToolInvocation 终态、审计、Outbox 与该事实事务尚未完全统一，跨进程幂等派发/owner fencing 也未交付。

## 验证范围与后续消费

原 bare passed 负测、真实 PG/MinIO 的步骤字段丢失、执行成功后 Run 保存失败留下证据，以及执行期间上下文改变，均保留红测日志。最新专项包括真实 Node HTTP/Chromium、Unicode、完整请求 hash、成功/失败/超时/导航、正式/兼容路径、真实 PG 原子回滚/重试/篡改拒绝。目标页面是明确的隔离 HTML 协议夹具，**不是 exweb 服务或维护者批准的业务 oracle**；测试数量、终态和命令错误分别见[实施记录](./implementation-progress.md)。

真实 exweb 的固定 Git 文件、画像成员和 context/scope/generation/mapping 验证仍单独记录。[独立真实运行](./exweb-native-runtime-validation.md)已使用生产 HTTP oracle engine 观察固定 JAR，但没有把那些开发检查接入本节的原用例 RunPlan 归档；静态来源、本地协议夹具和 exweb 原生检查不能拼接成正式业务覆盖。

继续交付的消费链必须连接已审阅 mapping、确切 case/step/oracle、预算化生成的脚本修订、DOM/API locator 证据、target build/commit、环境和 fixture/setup/cleanup，保存独立 RunPlan。Runner 回执随后才能作为这个固定计划的一次观察，回流到真实覆盖和 ReleaseContext；不能只把 `business_coverage_verified` 改为 true 或用通过数量推导放行。完整旧链切换、五用途、自动增量、独立 gold/安全/容量/性能与真实 exweb 试点继续是原目标的必需交付。

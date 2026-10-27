# 固定来源的构建入口与缺码恢复

状态：2026-10-08 已实现有界的中英文直接请求、Project Overview 引导入口和缺少代码时的原 Goal 恢复。它们共用 application 编译器与 ToolInvocationRuntime，不调用旧可变物化或自动发布流程。完整自然语言解析、维护事件和本方案 P0-P6 验收仍未完成；真实验证范围见[实施记录](./implementation-progress.md)。

## 已采集输入的入口

`Build the system image for this project.`、`构建系统画像` 等完整独立请求表达当前项目的一项构建意图。initialize/enrich/refresh/repair 模式通过确定性解析取得；问题、引用和混入额外动作的文字不能落回旧 substring 编译器。原用户文字保留在会话，按钮语言变化不改变构建目标。

也接受明确的来源类别描述，例如 `Build the official system image from code, US docs, and tests`、`Initialize the system image from code, US docs, and test assets` 和 `基于代码、需求文档和测试用例构建当前项目的系统画像。`。code／requirements／tests 及其有限中英文同义词只描述类别，不筛选 binding、引入新 URL／路径／凭据或改变来源权限；仍固定当前项目完整已采集 manifest。重复类别、未知类别、多行、超过 2048 字符或夹带部署／发布等额外动作需要澄清，不能截取其中合法片段执行。

application 从当前账号可访问的来源和会话版本解析输入：项目级会话必须恰好有一个 official 目标，版本级会话必须恰好有一个对应 version_working 目标。歧义需要明确选择，不按列表顺序猜测。目标固定 baseline/version 和已核验的 nullable publication head/image hash，最新已采集 manifest 的全部 binding 均需授权。需求和历史测试可选，不要求三类来源齐全才能构建结构候选。

版本会话里的 `official` 请求需要显式选择官方目标，不默默改为该版本的工作基线。不同语言或来源类别描述规范化为相同 mode/objective，只要目标、来源及原请求仍吻合，就复用原 Goal；这一有界规则不是任意自然语言解析。

准备阶段只读、不采集、不索引、不调用模型。Goal 的初始工具只有 `system_image.build.plan`，固定完整 request digest；保存成功后核验原 canonical 命令和不可变计划，再追加原计划查询、独立结构预算确认和结构执行。一次结构许可只允许一个工作项、零模型调用和零模型费用，不能因为计划里有建议预算就执行。

普通准备引用依次固定 project、source manifest、target 和 request digest；保存回执核验后另加 plan ID/digest，共六项。已有活跃 Goal 必须重新核验原请求才能复用，不能换目标、换来源或创建平行控制器。

## 缺少代码时保留原目标

必需代码未采集时，仍在恰好一个已核验目标上创建原 `system_image_build` Goal，暂停原因为 `missing_captured_code`。原请求只包含 project、规范化 objective、mode 和完整 target；字段不可增加或省略。

此时唯一工具是带 `build_input_request` 的 `query.system_image.status`。该特定查询返回本地状态摘要，不经过模型回复出口。目标引用只包含 project、target 和原等待请求 SHA-256，共三项；没有 BuildPlan、执行授权、结构工件或模型调用。普通状态查询仍保留原回复行为。

查询命令本身已完成；等待补源属于 Goal 的暂停状态及对应 blocked step，不能把成功的查询回执改成失败或 follow-up 命令。补源恢复时保持原查询输入、invocation 和 completed 回执，不重新查询来替换原证据。

用户通过独立的来源登记/采集命令补齐代码。采集不是结构预算确认；可选文档和测试缺失继续以 gap 保留。补齐输入后支持两种继续方式：

1. 显式继续原 Goal，提交用户看到的完整 checkpoint。
2. 再发当前项目的同一有界构建请求，由服务端固定原等待 checkpoint 并复用原 Goal。

继续前回读原状态查询的持久 ToolInvocation，核验 goal/conversation/project、完整原请求、completed 状态及精确项目回执。目标、权限、请求摘要或原回执改变均拒绝，不能用新状态查询替换原证据。

补源只将最新获授权的 captured manifest 固定到原 target/objective/mode，并保留原等待 digest。原状态查询的 input/invocation 和 workflow ID 不变，追加一个 canonical plan 保存步骤。完整 Goal 条件写入与原 checkpoint 消费沿 0085 的同一 PG 事务提交；仍未采集代码时不消费 checkpoint。

此时引用为普通四项加原等待 digest，保存计划后共七项。继续成功只推进到独立结构预算 gate，不创建结构执行许可。旧等待 checkpoint 的重放只回读当前状态，不确认新预算；新预算需要用户另行确认。

已消费的补源／结构继续 checkpoint 可以只读重放；预算确认不是同一种消费回执。原预算 gate 已推进到候选审阅后，再提交旧预算快照返回 `409 agent_checkpoint_changed`，不得借兼容恢复确认下一动作。

0089 的[主动运行预算](./agent-active-runtime.md)使新 Goal 的补源/确认等待不再耗费运行时长，恢复保留已用毫秒和首次起点；耗尽预算仍须独立增加上限。旧 Goal 和 v1 检查点保持原语义，不虚构历史主动消耗。

## 前端回执与恢复

Project Overview 的输入面板识别 `missing_captured_code`，明确代码必需、需求和历史测试可选；等待输入不展示工具确认按钮。来源采集后继续同一目标，保留原会话、原 Goal 及目标选择。

前端不能仅凭“七项引用”认定这是合法恢复。它重新 GET 原状态查询和原计划保存回执，校验原等待摘要、对象范围、固定计划及完整工具 prefix。失联、错配或刷新只读恢复，不自动重发 POST、重新采集或确认下一 gate。沿用共享深浅色、移动端和无滚动条布局，不修改全局视觉 token。

## 原调查成果的只读审阅入口

`build_completion_review` 展示指向原 Goal 和原调查 invocation 的 Knowledge 链接。入口依次执行七次私有只读查询：原 Goal checkpoint、原 canonical 调查命令、该命令保存的调查修订、原 BuildPlan、报告固定画像的最小来源成员页、原目标 baseline/version、再次读取原 Goal。每步核验完整 scope、ID/hash、输入及回执，不能按最新候选或列表顺序替换原画像。

审阅路由不加载全量 `system-image`、release-readiness、解释、记忆或 Swarm 详情，也不展示它们先前缓存的数据。会话只 GET 已有记录，不调用隐式创建 POST；检查过程中原 Goal 改变、来源撤权、回执损坏或原目标 version 改变均隐藏结果。刷新或重新加载只回读，不补写记录、不确认 gate、不完成原 Goal。中英文使用同一领域读取链路。

发布面板只提供原 BuildPlan 的目标，不查询全量基线再选择最新目标。历史调查允许该 baseline 的 publication head 已经改变；独立发布命令仍重新读取当前 head，并分别确认审阅及 CAS 发布。知识发布不授予业务规范、质量生成、目标执行或 release 权威。关闭审阅清除两项 URL pin，恢复普通 Knowledge 导航。

SSE 的消息 reducer 立即处理事件；关联查询的重新读取使用 200ms 首事件窗口及每 query key 的 single-flight 合并。进行中的读取不被重放事件反复取消；必要的后续读取在原请求结束后执行，卸载后不继续排队。该读取合并不改变 canonical SSE、Outbox、版本 pin 或当前权限校验，也不是性能门禁证明。

## 授权及剩余范围

状态查询、来源采集、结构预算、证据调查、语义审阅和正式发布是不同动作。结构候选完成后仍需独立调查确认与完成审阅；不能从代码对象数量推断业务正确、用例覆盖或已正式发布。

Goal explanation 将缺码、结构候选、新阶段准备和完成审阅分别说明为来源采集、候选审阅、新计划审阅和完成审阅。pending/running 的当前状态优先于历史暂停原因与旧工具 gate，追加阶段只描述 active phase 的步骤；completed/cancelled 不提示恢复或确认，failed 要求检查失败后另建目标。说明接口只读保留原工件／命令／审计，不授予来源、执行或发布许可，也不把用户暂停等同于结构工具的独立停止命令。

当前入口是明确且有界的直接请求，不等于任意自然语言目标解析。新 URL/凭据、指定另一版本、复杂多动作、维护事件、动态反证调查和全计划多能力预算仍需要后续能力。创建/审计/Outbox 全事务、其余恢复的 owner fencing、来源 cutover/lineage、多格式、自动增量/overlay/合并、五用途/旧生成链切换、脚本/RunPlan 与真实执行反馈及独立 gold/性能仍保留完整目标。

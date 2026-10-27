# Agent 主动运行预算与恢复契约

更新：2026-10-08。0089 修正新 AgentGoal 将等待补源、确认和审阅时间计入运行预算的问题。它实现原目标持续累计的运行态计时，不是完整多能力授权、费用账本或全部恢复分支的 owner fencing；完整范围仍以[自主系统画像主方案](./autonomous-system-image-design.md)为准。

## 计时语义

新目标由 application 创建时设置 `active_runtime_ms=0`。`active_started_at` 保存当前运行区间的 UTC 起点，`started_at` 继续表示目标首次启动时间，不因暂停、恢复或追加构建阶段改变。

- 开始执行时只开启尚未开启的区间；运行态重试不能重置起点。
- 检查预算使用累计毫秒加当前区间时长。暂停后不再增加，不能以更改 `started_at` 或重新启动来清空已用预算。
- 治理 gate、缺码/后续输入、预算暂停、用户中断、构建完成审阅，以及完成、失败、取消，均结算区间并清空运行起点。
- 恢复同一目标后继续累计；短于一秒的执行按毫秒保留。达到原上限仍暂停，只有独立提高预算才能继续，不因恢复自动追加额度。
- 未持久化暂停的 running 目标保留原起点，重启期间保守继续计时。该计时是运行状态的墙钟区间，不是 CPU 使用量，也不声称已能精确扣除所有 Worker 停机或任务队列时间。

代码索引、结构任务和 Provider 自身的 timeout、文件/字节及工作项上限保持独立。该计数不批准下一工具、不继承模型出口许可，也不改变原 plan/grant 的范围。

## PostgreSQL 与历史兼容

`0089_agent_active_runtime` 只给 `agent_goals` 添加 nullable `BIGINT active_runtime_ms` 和 nullable `active_started_at`，检查非负值及区间必须有计数器。不从 `started_at / last_progress_at` 猜测旧记录主动运行量，不默认回填零。

旧目标两字段均为空，保持原墙钟预算语义；序列化省略新增字段，已有 Goal JSON、v1 checkpoint digest、启动回执和历史工件不变。新目标同时返回两个字段，使用 `nasus.agent-resume-checkpoint.v2` 固定整个 Goal 和运行计时。队列 pin 的五字段外形及消费回执契约不变，正常重放不改写旧事实。

条件恢复事务读取原 Goal 后核对全部状态，计数器的并发变化同样导致 checkpoint conflict；计时与恢复步骤、原 digest 消费沿同一 PG 提交。该保障只覆盖已有条件提交链，普通生命周期写入仍不具备完整全局 owner fencing。数据库已有主动计时记录时，降级明确拒绝丢弃字段或 v2 检查点依据。

## 消费与验证边界

API Goal 快照、SSE 完整 Goal payload 和 explanation budget 返回持久字段，Portal 类型保持可选以兼容旧记录。前端不自行推算消耗、修改计数器或重新签发 checkpoint；确认仍重新读取服务器权威状态，不自动重发未知结果的写请求。

验证包括固定时钟的多次暂停/恢复和毫秒累计、全部结算出口、用户中断先持久化后发布、运行态序列化恢复、严格坏计数/时区拒绝；真实 PG 的增量迁移/降级保护、旧摘要、条件消费和并发计数变化；Local/LangGraph PG 的长等待、耗尽预算及原目标补源；真实 Temporal Worker 更换/Activity 重试、Portal 深浅色/窄屏及固定 exweb 原生索引。每批实际终态见[实施进度](./implementation-progress.md)，专项不相加为全量门禁。

exweb 的需求和测试使用明确标记的伴随验证资料；不执行目标仓库，不以结构对象数、测试契约或计时证明业务准确率和真实覆盖。完整 P0-P6、多格式/cutover、动态语义反证、自动增量、五用途上下文、旧链切换、脚本/RunPlan/真实执行反馈、独立 gold 和性能仍待交付。

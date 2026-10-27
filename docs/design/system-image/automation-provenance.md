# 自动化脚本与审阅的派生追溯

更新：2026-10-11。0100 为已保存脚本和独立审阅登记原始上游依赖，连接既有测试设计派生图。它不修改旧画像、ContextPack、用例、覆盖矩阵或审阅摘要，不授予目标执行权限，也不替代完整 [P0-P6 交付](./delivery-and-evaluation.md)。

## 原始依赖

每个脚本登记精确的 project/context、脚本修订和工件摘要、canonical invocation、事实元数据摘要及原生调用来源摘要。直接父集合包括原 context、scope、generation、coverage、mapping 和全部选中 case。用例的完整内容摘要包含步骤和 oracle，不能用当前工作区或重新生成的同名用例替代。

每个父项分别保存工件摘要和登记摘要。前者固定原始内容，后者固定项目、上下文、调用及父关系；只有 ID 相同不足以证明历史依赖相同。脚本的原生来源摘要还固定原 reservation、native reply、call ID 和 response hash，不复用 Provider 的外部 ID 作为 Nasus 事实身份。

审阅登记连接原脚本；第二项及后续审阅还连接确切前驱。接受、拒绝、暂缓及撤回均保留原历史，旧事件重放只核验该事件对应的历史前缀，不跟随今天的审阅头。完整接受仍保持 execution_authorized=false 和零 automated/executed_on_target/passed。

## 保存和读取

PG 新增 `quality_automation_provenance` 和 `quality_automation_provenance_edges`。同项目、context 和端点登记摘要的复合外键分别连接原测试设计登记或脚本登记；节点另连接实际脚本、审阅和 canonical command。数据库拒绝 UPDATE/DELETE，并提供按父项反查的索引。

新事实、追溯登记、审计和 Outbox 在原业务事务中提交。任何登记失败均回滚新事实，不删除已经发生的模型预留、调用费用和私有回复归档。已归档回复的内部重放仍由原服务核验；该登记不增加模型重发或公开恢复入口。

脚本/审阅读取、已有命令恢复和 Outbox 投影仅验证原登记。节点或边缺失、摘要错误或父关系不一致时拒绝，不能借正常读取、新审阅或事件重放修补旧历史。完整原文、MinIO 归档和当前角色/来源 ACL 仍由 application ports 重新核验，元数据登记不是访问授权。

脚本最多固定 512 个选中用例和 5 个其余父项。原测试设计节点及其边按完整 ID 集合批量查询，不使用公开影响预览的 128 节点视图替代。全量元数据验证不等于已经达到数据库容量或端到端 p95 门禁。

## 历史迁移

0100 明确固定建表 DDL，不从以后可能变化的 ORM 表定义生成旧 schema。迁移按原脚本、完整有序审阅前缀显式回填，旧 v1 派生图的六类节点、父集合、摘要及 API 契约保持不变。

回填只消费原事实元数据，不读取新模型、当前发布头、可变工作区或私有对象正文。坏事实或原登记不一致使 DDL/回填事务失败，不跳过记录。正常路径不调用 backfill；非空登记禁止破坏性降级。真实 PG 的迁移验证必须包含已有脚本/审阅，空库升级不能代替历史迁移验收。

历史迁移演练在当前最新 schema 上使用独立测试数据库、明确的 PostgreSQL 回滚事务。
仅临时解除后续表指向待重建表的直接外键，不删除 RunPlan、构建、环境、健康或定位表，
不使用 CASCADE，也不解除后续表的其他外键。演练仍重建完整 0100 DDL、核对 ORM/schema
契约和原全部脚本/审阅/派生摘要，并验证坏事实拒绝。事务退出后全库外键清单必须恢复；
独立辅助测试包含已填充的子表和孙表，回滚后实际非法引用仍被 PostgreSQL 拒绝。
这只是测试演练适配，不修改已发布迁移、生产数据库或任何业务批准/执行事实。

## 验证与剩余范围

`test_automation_provenance.py` 验证显式 v1 摘要、全部必需父项和 517 项上限；`test_automation_provenance_repository.py` 验证两个批量元数据查询及末项损坏拒绝。这些纯测试不证明真实数据库容量或外部模型效果。

`test_automation_provenance_api.py` 使用隔离 PG/私有 MinIO，覆盖实际 canonical 生成、独立审阅/撤回、事件重放、追加式和精确 hash 外键、正常读不修补、故障回滚及 populated migration。固定 exweb 专项核验原 126 个 Git blob 和全部选中用例依赖；其模型传输及需求/oracle 是明确的协议 specimens，不是维护者批准的业务 gold 或目标执行。实际批次、失败和加载范围见[实施记录](./implementation-progress.md)。

0101 的[执行计划准备](./run-plan-preparation.md)通过复合外键连接原脚本/审阅登记的确切 project/context/node/hash。它只保存完整输入与目标声明，尚未验证构建、环境或 fixtures，也不授权执行。

该桥接尚未扩展公开 context impact/invalidation 的 v1 图，不能声明统一项目 delta DAG、自动失效/重建或完整 P4 已完成。automation ContextPack、公开脚本任务生命周期、完整目标核验的 RunPlan、canonical 目标执行与真实覆盖/放行、五用途/旧链切换，以及独立 gold、安全、容量、性能和试点仍是原目标的必需交付。

# 原目标环境的健康检查端口

更新：2026-10-11。此增量补齐 P5 执行前检查的原实例健康观察，不替代完整执行、覆盖、发布或 P0-P6 验收。

## 原输入与防腐层

`RunPlanEnvironmentHealthApplicationService` 已在 production container 组装。0106 新增独立 `quality.run_plan.record_health` / `query.quality.run_plan_health_record` 与重新授权的历史 GET；实际 canonical PG/私有 MinIO 回归及固定 exweb 的新 canonical 归档专项均已终态通过。Portal 已接入下述独立健康审阅。后续正式执行生命周期通过 application port 消费，不能绕过 ToolRuntime 的独立执行确认。检查本身只有固定只读探针，不部署、修复、初始化 fixture、执行用例或调用模型。

请求沿用确切 project、原 RunPlan ID/hash 和原 build binding ID/hash。完整原计划、构建与来源访问权先于任何 Docker 操作校验；原输入必须 current，当前账号必须具备 reviewer 角色。目标只能是原声明的 operator-owned local/8080 环境，资源和政策来自私有 registry，不允许请求指定容器、URL、SQL、数据库账号或路径。

领域 `NativeEnvironmentHealthObservation` 不依赖 Docker、ORM、HTTP 或框架。infrastructure 使用现有有界子进程，持续调用权限 callback；取消和撤权异常保留，故障不回显原子进程输出。组装复用原计划读取和 configured environment port，没有新增第二套 source/build repository。

## 固定探针与原始响应

- PostgreSQL：在确切原 PG 容器内、原非 root 用户下执行 `SELECT 1`。连接固定为 localhost:5432，用户名和数据库名必须为非空 ASCII 标识符，不能借 dbname URI 切到外部连接；禁用 psqlrc/service，连接和语句有超时。密码只在该 PG 容器内部环境传递，不进入宿主 argv、返回值或日志。
- Redis：在确切原 Redis 容器内执行 localhost:6379 的 `PING`，只将原 `PONG` 响应识别为健康。
- 应用：在原只读 JAR 容器内 GET 固定 `/actuator/health`，禁用 curl 配置、代理、重定向与重试，并限制协议、时间和完整响应字节。仅原 HTTP 200 且严格 JSON 的顶层 status=UP 识别为健康。

三项响应必须完整且有序，分别固定 role、探针版本、container/image/StartedAt、原字节 base64、byte count 和 SHA-256。重复 JSON key、畸形/不完整响应、缺项、换实例、换响应 hash 或布尔数量均拒绝。实际有效的 DOWN/500 等保留为不健康观察，不改成 passed。

探针前后均重新检查完整原环境和实际挂载 JAR。StartedAt、原网络、任何依赖或 JAR 改变则拒绝整份结果；registry 政策及原计划/构建/ACL 在返回前再次检查。历史 inventory 的所有 v1 字节、hash 和 false 权威字段不修改。

## 权威与剩余交付

`dependency_health_verified` 只表示这次确切 PG/Redis 的固定探针响应，`target_health_verified` 只表示应用报告的健康状态；它们不是持久化业务行为、数据留存、业务 oracle、真实测试覆盖或长期健康证明。只读 SQL 不证明应用把会话写入 PG，health=UP 不证明授权或关闭行为正确。

完整 observation 不进入共享 Conversation/SSE。0106 将完整原 inventory 与三份响应私有归档到 MinIO，独立健康元数据、原 Plan/build 复合 FK、认证 actor/command、审计和 metadata-only Outbox 同 PG 事务登记。未确认、确认过期、原来源撤权、换父输入或工件损坏不能登记；实际有效的不健康结果仍可如实保存，不自动改成健康。

`GET /v1/projects/{project_id}/quality/run-plan-health/{record_id}` 为 private/no-store，每次读取先重新检查 reviewer/原来源，再完整核验归档字节和摘要。查询、相同已提交命令重放和事件回读不得加载 registry、重新探测 Docker 或补写旧事实。Agent 只能消费重新授权的 metadata 回执，不隐式读取原响应。0106 是追加式新表，没有 JSON 导入或自动回填入口，非空降级拒绝丢弃历史；开发专项 JSON 不可导入为正式证明。现有 0105 的 `dependency_health_verified=false`、原字节和摘要保持不变。

返回仍明确 `historical_not_live=true / environment_fully_verified=false / execution_authorized=false / fixtures_verified=false / locators_verified=false / business_coverage_verified=false`，正式 automated/executed/passed 全部为零。物理出网/宿主拒绝、fixture/setup/cleanup、定位、独立执行授权、PG owner/lease、取消/恢复、逐 case/step/oracle 回流和正式覆盖仍继续实现。

## Portal 独立审阅

原生构建关联下增加独立的健康面板，默认收起，不因打开计划或原环境观察自动提交命令。每次新检查须单独勾选完整原 Plan/build 请求；环境登记的确认、命令 ID 和 sessionStorage 定位不能代替健康确认。健康与环境使用共同的 canonical API/recovery 状态机，但 tool、UUID 命名空间、receipt、query key 和恢复存储命名空间各自固定。

前端从原归档重新计算 inventory、health、request 和 artifact hash，核验确切实例 ID/image/StartedAt、全部有序响应及响应字节 SHA-256。应用响应使用严格 UTF-8/JSON，拒绝重复字段、Unicode 转义后的重复 key、无效 HTTP 状态及非完整 JSON，不仅依赖 metadata 的 healthy。PG/Redis/应用的健康结果分别由原响应派生；有效 DOWN 如实展示异常，不拒绝真实不健康记录，也不改写原 0105 的 false 字段。

默认展示三项结果、观察时间和原记录摘要，完整 inventory/响应折叠。失联恢复只 GET 原命令及 private/no-store 原归档；刷新不重复提交或代为确认。sessionStorage 仅保存同账号/项目/原父请求的 ID/hash 定位，不保存原响应、清单、URL 或凭据，不能作为访问许可。上游不再 current 时只允许看历史，不新增探针；归档损坏或撤权时父计划及受保护内容隐藏。当前 UI 定位最近原命令，并非跨账号或全量历史清单。

## 验证

`test_owned_target_health.py`、registry/application 和边界测试使用明确 protocol specimens，覆盖固定命令、原健康/不健康响应、错实例、重启/JAR 变化、撤权、源/政策变化、坏字节和 SQL 连接标识。它们不代表实际数据库或目标运行。

固定 exweb 的内部健康专项已终态 **1 passed / 2590.25 秒**（`output/exweb-canonical-original-health-current-20261011.log`）。原始报告实际回读：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、全部 126 个 Git blob、原 JAR `sha256:ebfb0f316c6a9068b7c6682c308e83fff8147d97839ec4c737285efca7b490ea`；实际 SELECT 1、PING、actuator-health 均健康，health digest `sha256:afff3a8831d7d8e686a95ae413bca642256580b855ac7b8d7c6b286bee4ad3d0`。原 0105 登记完全不变，资源和 registry 删除后历史回读没有 Docker；cleanup verified=true/remaining=[]，实际 owner 容器列表为空。

该批加载早于 0106，报告明确 `health_is_internal_not_independently_registered=true`，不能作为新 canonical 健康归档的验证证据。实际构建/PG/MinIO/Docker 与模型、调度、需求及业务 oracle 的 protocol specimens 区分；不同批 JAR hash 不同，未证明可重现性、业务正确或正式覆盖。新 0106 PG/MinIO 验证状态见[实施记录](./implementation-progress.md)。

新 canonical PG/私有 MinIO 专项 **1 passed / 1229.70 秒**（`output/original-health-record-canonical-pg-20261011.log`），包含确认过期先于原探针、晚期事实/审计/Outbox 同事务回滚、完整历史回读及 Agent 回执、实际 FK、append-only/非空降级保护、损坏和来源撤权。其 builder/model/Docker response 是明确 protocol specimens，不是实际 exweb 运行。

新加载的实际 exweb canonical 专项 **1 passed / 4017.41 秒**（`output/exweb-canonical-health-record-current-20261011.log/json`），session5491已结束，32239/32261均退出。原commit/tree/126文件和 MinIO JAR `sha256:6b6471b6f181809fd26376b5cfd073f9231a8276893ca011fbb81f2040f91f36` 经真实 Java/PG/Redis 及新独立确认得到健康登记 `081a923d-46b0-51ac-a73b-93569ba3a979`，health digest `sha256:d57d5cd195628fe3298180897727ffc5682094e7b1f75bf16bfd402313b396c6`。三份原响应2/5/19字节且健康true，0105 原记录不变；目标/registry清理后的原私有 GET和query未再次Docker，cleanup verified=true/remaining=[]、原代码导出删除。模型、调度、业务oracle仍为protocol specimens，无外部模型、正式执行或通过覆盖。4017.41秒是整个专项时长，不是单请求或p95性能。

独立开发脚本后续增加[有界隔离 canary](./native-isolation-canaries.md)，真实三项比较另有终态证据，但与上述canonical批不同源工件实例，不能拼接或导入为同一次健康/执行许可。全部出口/宿主接口政策、fixture/定位、持久执行生命周期和完整P0-P6继续待交付。

Portal 健康与原环境专项 **92 passed / 1516.567834ms**，完整 contracts **1036 passed / 5546.605167ms**，DDD/Portal/native 边界 **159 passed / 3.69 秒**；范围重叠不相加为项目总量。导航/RunPlan 浏览器 **11 passed / 1.7 分钟**，两主题覆盖独立确认、丢失两类回执、只读恢复、真实 DOWN 协议字节的异常展示、撤权隐藏和 390px 无新增横向溢出。四张 `health-record-{light,dark}-{desktop,mobile}.png` 已实际视觉检查，响应默认折叠。浏览器 transport 是协议 fixture，不证明 native Docker 或外部模型质量。build/lint/i18n 退出 0，smoke success；初次 build 的 typed instance index 错误已修正，失败日志保留，主包 1209.56 kB 的警告不隐藏。

回读入口后续加固：即使消费方没有先走恢复函数，私有 GET 前也重新校验完成命令的确切 tool、确认布尔值、原五字段输入、request hash、result invocation 和 object refs；环境命令不能携带健康 receipt 冒充。错配在读取原字节前拒绝。新加载的完整 contracts **1036 passed / 6078.851958ms**、导航/RunPlan **11 passed / 1.7 分钟**，build/lint 退出 0，主包 1209.84 kB / gzip 327.65 kB 警告保留（`health-record-portal-*-pinned-read-20261011.log`）。上述前批不是新 read 边界的验证依据；完整真实目标执行、正式覆盖及 P0-P6 仍未完成。

# 画像对象来源依赖契约

更新：2026-10-07。0070 为固定画像登记完整的对象来源子图，支持从画像成员追溯到确切的来源、代码或文档修订和原文证据。它推进 P1/P4 的派生依赖底座，不代表全部语义、批准、检索、脚本和运行依赖已经登记；验证范围见[实施记录](./implementation-progress.md)。

## 节点与直接依赖

策略为 `nasus.image-object-provenance.v1`，节点键为 `kind:artifact_id`。项目、工件 hash、元数据 hash、完整来源 pins 和有序父集合共同参与节点登记 hash。

| 节点类型 | 直接父依赖 | 语义 |
| --- | --- | --- |
| source | 无 | 已成功采集的固定 SourceRevision，不指向可变来源 head |
| manifest | 全部已采集 source | 元数据摘要同时保留 failed/pending/legacy 成员，不伪造其修订 |
| code | 所属 source | Nasus 代码身份及修订，不用 Provider 私有节点作主键 |
| document | 所属 source；AC/规则另含父需求 document | 子对象和父需求必须来自同一 binding/revision |
| evidence | 所属 source | 确切原文定位及内容摘要，不复制私有原文或地址 |
| member | 固定 code/document 及该成员已冻结的 evidence | 不能因之后补充证据扩大历史成员集合 |
| image_objects | manifest 和全部 member | 独立对象子图根，避免冒充完整语义画像依赖图 |

未验证的旧观察仅登记其不可变 member 内容，没有经过验证的来源或实体父边。画像完整 artifact/membership hash 仍参与根摘要，但语义 assertion、review、authority 的祖先尚未在此子图展开；不能仅凭根 hash 声称可完整反查批准或执行依据。

## PostgreSQL 约束与原子提交

`image_object_provenance_nodes`、`image_object_provenance_edges` 和 `image_object_provenance_roots` 保存登记。边的两端通过复合 FK 固定同一项目、节点键和登记 hash；根同时固定原生 ImageRevision。反向父索引用于后续完整派生查询。

原生记录是登记依据，而不是 SSE 保留期。`system_image.candidate.frozen` 在原事实/Outbox 事务内读取刚提交的 manifest、成员、实体、文档及证据元数据，核验原 hash、类型、父子和证据归属后登记全部节点与边。缺父、漏成员或冲突使事实与登记一起回滚。投影不拥有 Session，不调用模型、存储或其他领域 repository。

0070 在同一迁移事务中回填已有画像，坏原生 pin 使 DDL 与部分登记一起回滚；登记表拒绝 UPDATE/DELETE，有数据时拒绝破坏性 downgrade。源数据可以分批读取和写入，不截断到影响预览的 128 节点或首批 256 项。

画像正常读取和重复冻结均核验登记，不能仅凭相同 artifact hash 返回成功。缺项或损坏返回脱敏完整性错误，不返回部分画像；当前账号和来源权限仍优先核验。PG 元数据审计不替代应用层对 MinIO 原文和归档的完整校验。

审计按每批 256 个键读取全部节点字段和父边，不为读取创建 Node/Edge ORM 实例。原生来源、manifest、代码身份/修订、文档、证据和成员也改用完整 ORM 列表达式读取，不分配对应实体实例；仍保留 autoflush，事务内待写变更不能因 identity map 或列读取而漏验。该优化不省略类型、元数据、hash、pin 或完整父集合比较，也不改变 v1 登记公式和事务边界。

节点 v1 摘要固定为项目、类型、工件 ID/hash、元数据 hash、来源 pins 和完整父集合，加策略版本。它们都是不可变标量或 tuple，直接构造原公式而不递归复制；结果与原 dataclass 序列化字节一致。未来增加 dataclass 字段不能改变历史摘要，新的登记语义须另行版本化。

v1 的证据身份摘要固定使用原有十二个字段，不反射 ORM 的全部列；新增原生元数据列及采集时间不会改变历史公式。定位、行号、内容和提取器字段仍全部参与摘要，私有地址只用于校验，不写入图。新的证据身份协议须另行版本化，不能静默改变此迁移投影。

## 编译局部只读快照

同一 ContextPack 编译会多次读取固定画像。重复核验根的全部父边时，每个节点只计算一次登记 hash，避免大根节点的平方级开销。

`verified_read_session` 为一次编译建立 PostgreSQL `REPEATABLE READ / READ ONLY` 快照，并在其中复用已完整验证的画像元数据，最多保留两个画像。嵌套会话独立建立快照，退出或异常恢复外层；失败结果不缓存。新预览、提交复核和历史读取使用新快照，重新检测损坏输入。

只读快照使用独立连接池，每进程最多四条连接、不溢出，池满五秒后明确失败，不占住用于实时 ACL/authority 的主池。每个应用读取仍检查当前 actor、项目、全部来源权限、policy fingerprint 和 ACL epoch；批准头、撤回状态及授权结果不进入快照缓存。验证后的私有 bytes 保持原有编译局部、按 actor/权限键隔离和复制返回的规则。

此复用提供一次编译的一致输入视图，不是永久授权票据，也不保证任何并发时刻都重新扫描同一快照。提交时必须新建快照并重新核验权威及权限；读取历史始终受当前 ACL 限制。有限池和少量实测不能代替并发容量或 context p95 门禁。

Portal 的分页连续性是另一层优化：只在同一项目、私有 read session 和固定画像下保留画像级面板实例，避免每页重新挂载。每个新页仍走实际 HTTP、完整 membership 与原文摘要核验；核验期间面板隐藏，旧行和分页控件移出 DOM，失败清空候选。不会跨会话/画像复用，也不增加敏感查询的缓存时长或重试。

对象与 membership 的同一 offset/limit 窗口并发读取，两者都完成且匹配后才返回页面。任一 401/403 或来源变化错误优先于容量错误；其他完整性/存储错误也不触发降载。仅明确的 `413 image_page_too_large` 可以在两次读取均结束后缩小窗口，避免旧请求与下一窗口交错；关闭后迟到的结果不能显示。

候选召回的完整文档读取和选中证据核验、语义输入的完整字段和原文准备，也使用同步步骤局部的 `verified_read_session`。原始召回嵌套于输入准备时建立独立快照并恢复外层；之后重新准备仍完整核验。screened recall 的审阅头筛选保持原实时复查，返回 corpus 不保留连接或授权。快照在准备返回时释放，不延伸到模型请求、确认、写入或历史读取，既有原文、字段、来源、预算和末次 ACL 检查不变。

批量证据读取按完整来源、修订、文件和 manifest pins 分组，同一固定原文只读取/解码一次，所有不同片段仍独立校验范围和 hash。每个独立文件读取前后以及整批开始/结束复查当前来源权限，不按片段重复读取，也不按每十六项才检查。撤权立即停止，不继续读取后续文件或返回部分证据；下一批重新读取原文，不跨请求缓存 bytes。元数据快照不包含实时 ACL。

### 编译局部对象存储连接

归档证据会话同时开启 `ObjectStorage.read_session`，同一存储实例在一次编译中惰性创建一个 S3 读取客户端。嵌套会话借用相同配置的存活连接；下一轮编译新建连接。共享的是传输连接，不是原文 bytes、角色、权限或批准状态：每次证据读取仍执行 GET、文件/片段摘要校验及应用层前后授权。

客户端使用独立 SDK Session 构造，不通过共享默认 Session；同进程内通过锁保护首次初始化，独立线程的 ContextVar 不互相继承。显式复制的存活上下文可借用连接，关闭后不能继续读取；父会话退出时仍在进行的读取持有 lease，最后一项释放时才关闭传输。PID 检查先于锁，拒绝跨进程继承的连接；配置变化也拒绝旧连接，必须显式建立新会话。这遵守 [Boto3 客户端并发约束](https://docs.aws.amazon.com/boto3/latest/guide/clients.html)，不将 SDK 客户端当成跨进程连接池。

读取完成、容量拒绝、异常或取消均释放响应体及所属会话；关闭失败仍复位 ContextVar，并保留先发生的业务异常。写入使用独立的短生命周期客户端，不借用读取连接或扩大操作权限。此改动不改变归档 hash、PG 事务、即时授权或业务事实，也不能单独证明 context p95/容量门禁。

## 与完整派生图的关系

0068 的[上下文派生登记](./derivation-registry.md)从 ContextPack 固定 image/manifest/query scope，再连接 scope、generation、case、coverage 和 mapping。0070 补齐 image 对象的来源祖先。两者当前通过原生固定 image ID/hash 和应用读取校验衔接，尚不是覆盖所有工件的统一完整 DAG。

后续仍需登记语义 assertion/decision、正式 AC/规则 authority、索引/检索 generation、脚本和 RunPlan 的直接依赖，交付完整项目变更计划、原子失效和增量重建。动态调查/预算、overlay/tombstone、合并/回滚、五用途 ContextPack、旧链切换、真实目标执行反馈、Provider 全生命周期/对照/gold/隔离及完整 V1 门禁继续属于原 P0-P6 目标。

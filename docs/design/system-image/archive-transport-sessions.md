# 归档传输作用域

更新：2026-10-08。系统画像的原文快照、冷回读与分块写入复用单次操作内的 S3 客户端，减少重复初始化和连接开销。此优化不改变来源清单、对象内容、权限、PG 事务或历史工件契约，不代表完整容量与性能门禁已经通过。

## 生命周期与隔离

`ObjectStorage.read_session()` 和 `write_session()` 分别拥有独立的 ContextVar 与延迟创建客户端。同种嵌套作用域只在配置完全一致、属于当前进程且未关闭时复用；未使用或本地文件操作不创建 S3 客户端。未显式开启作用域的单次读写仍自行创建并关闭客户端。写入不借用只读操作的客户端，也不修改读取生命周期。

作用域只复用 SDK transport，不缓存对象内容、来源 ACL、模型授权或业务结果。每个 PUT/GET 仍向对象存储发送原操作；GET response body 每次关闭。已关闭的复制 context 不能继续使用旧 transport，新的显式作用域可重新建立连接。独立线程不隐式继承别人的作用域；显式复制的活动 context 可共享同一 owned transport，最终活动 lease 退出才关闭它。

进程发生 fork 后，不获取继承的锁或复用继承的连接；旧 scope 读写拒绝，新 scope 创建自己的 transport。配置在活动 scope 内改变时，原读写失败；显式嵌套新配置建立自己的 scope，结束后恢复外层。失败、取消、工厂异常和 close 异常都恢复 ContextVar；已有调用异常不被清理异常覆盖。这里没有新增自动写重试或持久后台客户端。

## 系统画像接入

- 原文 `SourceSnapshotArchive.capture` 为完整文件集合和 manifest 开启独立写作用域；每个文件照常写入，最终清单仍固定全部引用及 hash。inventory 是独立操作，不与清单混淆。
- `SourceSnapshotArchive.materialize` 的 manifest 与冷文件下载使用一次读作用域。旧 checkout 仍逐文件检查原字节、路径和源 hash，连接复用不是跳过校验或内容缓存命中证明。
- `SystemImageRawAssetChunkApplicationService` 通过 `SystemImageWorkspacePort.artifact_write_session` 使用应用端口，领域和 application 不 import S3。Legacy 与 SQLAlchemy workspace 在 infrastructure 映射到 `ObjectStorage.write_session`。只有全部分块写入成功后，才替换投影中的完整 chunk 集合。

文件数量与字节上限沿用既有采集、快照和分块规则。本次没有并行下载、数据库批量注册、降低完整性核验或跨请求缓存。SDK 客户端仍使用既有凭据、配置和原生请求行为；transport 生命周期不授予权限，也不保证 SDK 级 exactly-once。

## 一致性与验证范围

原文、manifest、分块、来源修订与画像 hash 的算法不变，历史记录不迁移或重写。新的 Provider 指纹会包含已改变的投影源码，旧执行命令仍不得借重试替换依赖策略。S3 写与 PG 不构成分布式事务；失败可能留下未引用对象，完整保留与 GC 仍待交付。

纯测试覆盖 nested/standalone/local、读写分离、每次新字节、配置变更、关闭 context、线程和显式复制 context、进程边界、取消与清理异常。快照测试逐对象计数并保留损坏 checkout 拒绝，分块测试在第二次写入失败时不发布部分集合。固定干净 exweb 的实际私有 MinIO 组逐项读取 126 个文件和 135 个 chunk，第二个全新 materializer 再次远程恢复，客户端计数来自真实 SDK 调用包装而不是接口返回的成功计数。具体时间和浏览器/API 终态见[实施记录](./implementation-progress.md)。

单次本机测量不是 p95、大规模容量或独立业务 gold。验证不执行 exweb、Maven、目标 hook 或依赖安装，也不把静态源回读升级为测试通过或发布质量。

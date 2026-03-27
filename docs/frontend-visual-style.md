# 前端视觉与交互规范

说明：本文已参考 2026-03-18 登录后的 Google AI Studio `https://aistudio.google.com/prompts/new_chat` 实际页面结构，提炼其布局节奏、信息密度和控件语言，用于指导 Nasus Portal 的视觉与交互设计。本文不是像素级复刻，而是对其工作台气质和壳层结构的工程化转译。

## 1. 视觉方向
- 以 Google AI Studio 的沉稳暗色工作台为参考：深灰背景、低对比边框、分层卡片、左侧导航、中心大画布和右侧设置面板。避免过度鲜艳配色，突出内容中心区的微光聚焦。
- 将视觉语义分为三类：`探索`（Welcome / Build / Dashboard / Documentation）、`工作`（Project Space / Personal Workspace / Runs / Knowledge）、`治理`（Governance / Approval / Release Readiness）。每类保持一致的色调与动效节奏。
- 除暗模式，还需提供亮模式。亮模式使用米色、浅灰背景，保留相同层级关系（导航暗、主体亮、控制面板暗）以防干扰。

## 2. 布局框架
- 采用 3 列基础布局：`左侧导航`（232px 固定）、`中间主工作区`（自动拉伸）、`右侧控制面板`（320px 固定）。两条竖向分割线使用 1px 低对比边框，不依赖大阴影切列。
- 顶部不设全局浮动 header，采用左侧导航作为全局入口；主工作区内部使用“局部标题栏 + 内容画布”的壳层结构。
- `Welcome` 页面保留 AI Studio 风格的大面积留白：中心是单句 Hero 标题和能力卡片，底部是固定式输入/发起面板。`Build`、`Dashboard`、`Documentation` 共用顶层壳层；进入项目后切换为 `Project Space` 内容驱动视图。
- 行动按钮组、图谱、时间线、证据卡片等均在主工作区内组织，使用 12px/16px/24px/32px 间距系统，不做满屏瀑布流。

## 3. 实际参考页面结构
- 左侧导航分为三段：品牌区、主导航区、底部工具区。底部工具区容纳 `What's new`、设置、账户等低频入口。
- 中间主工作区具备极强的“空态构图”能力：在没有任务时，界面以大标题、功能卡片和底部输入框构成中心视觉；进入任务后，同一位置切换为任务画布。
- 右侧并不是泛化的“信息面板”，而是持续存在的参数/策略面板。AI Studio 里这里承载模型、温度、工具开关；Nasus 对应承载策略快照、证据范围、运行级别、审批动作和人工 override。
- 底部输入框不是简单表单，而是主工作触发器。它需要支持文本输入、工具按钮、上下文 chip、附加材料和主操作按钮组合。

## 4. 导航与侧栏
- 左侧导航采用“品牌 + 文本导航”为主，不是只放图标。背景色 #111318，选中项使用略亮底色和细边框，而不是饱和高亮块。
- 每个导航项支持 badge（状态/未读）与 mini-progress（任务收敛率），使用 14px 字体、70% 透明度；底部工具入口与主导航视觉上分组。
- 顶部品牌区保留系统名称、当前空间或版本切换；底部显示用户头像、设置与辅助入口；提供“快速新建 task/session”按钮（圆角 pill）。

## 5. 主工作区（Welcome / Build / Dashboard / Project Space）
- 背景采用 #0f1218，区域卡片深度通过多层阴影（`box-shadow: 0 15px 30px rgba(0,0,0,0.35)`）体现。
- 卡片采用圆角 18px，内边距 24px，卡片之间垂直间距 16px，卡片顶部可插入水平步骤条或状态条。
- `Welcome` 的 Hero 标题可放大到 48px-56px；常规页面标题为 24px-28px，次级标题 18px semibold。
- `Build` 聚合 `Create Project` 大卡、导入区块和初始化计划，并在底部保留固定式输入框。
- `Dashboard` 使用“统计卡 + 项目卡片网格 + 风险/阻塞列表 + 底部输入框”的结构。
- `Personal Workspace` 使用“US 头部 + 对话流 + Quality Asset Pack + Agent Goal + 底部主操作输入框”的结构；输入框用于发起补充分析、追加材料、请求重新生成，而不是单纯聊天。
- `Knowledge` 使用“图谱/列表 + 对象详情 + 证据细节”的双层结构；`Runs` 使用“运行列表/时间线 + 运行详情 + 右侧过滤/放行”结构；`Governance` 使用“列表 + diff/detail + 放行面板”结构。

## 6. 右侧控制面板
- 控制面板背景 #14181f，具备 2px 内边距的 separator 线，线条使用 30% 亮度。
- 分节标题 12px 大写；每节下方放置 toggle/checkbox/slider/select 控件，控件颜色使用 #5d80ff。
- 面板应采用“卡片堆叠”而不是长表单直排。每张卡片可以是策略摘要、参数设置、证据池、审批动作、环境快照。
- 控件包括：策略切换（toggle）、证据筛选（multi-select pill）、运行级别（tab）、温度/推理强度 slider、上下文范围选择、执行开关、审批说明输入。
- 控制面板提供“证据池”“策略快照”“人工 override”区域，默认折叠，可展开。
- 右侧面板 tab 不是全局固定值。至少要支持：
  - `Welcome`：`Activity / Tips / Status`
  - `Build`：`Projects / Imports / Health`
  - `Dashboard`：`Alerts / Progress / Activity`
  - `Documentation`：`Topics / Templates / Updates`
  - `Personal Workspace`：`Assets / System / Runs`
  - `Knowledge Gallery`：`Graph / Objects / Search`
  - `Runs`：`Active / History / Failed`
  - `Governance`：`Pending / Resolved / Policy`

## 7. 底部输入框与操作区
- 底部输入框固定在主工作区底部中央，宽度建议 720px-960px，最大不超过主列宽度的 82%。
- 输入框容器使用深色卡片式浮层，内部支持文本输入、多行扩展、工具按钮、上下文 chip、上传入口和主提交按钮。
- 输入框前置按钮用于“工具/附加材料/引用上下文”，后置按钮用于“发起分析/继续执行/申请审批”；不同页面沿用同一组件骨架。
- `Build` 页面中输入框承担“开始一个项目创建任务”；`Dashboard` 页面中承担“询问组合进展与风险”；`Personal Workspace` 页面中承担“补充上下文并请求下一步动作”；`Runs` 页面中承担“请求归因/重跑/提交放行”的快捷动作。

## 8. 组件规范
- **卡片**：背景 #1a1d24，圆角 18px，阴影 0 30px 60px rgba(0,0,0,0.35)，border 1px solid rgba(255,255,255,0.03)。
- **列表**：条目间隔 12px，hover 使用 #20252c 背景；左侧显示状态色带（5px），根据状态使用成功/警告/中性色。
- **表单**：输入框背景 #0f1016，边框 1px solid rgba(255,255,255,0.1)，输入文字 16px，placeholder 60% 透明度；聚焦时边框与阴影加强。
- **状态标签**：使用 pill 样式，success #38d9a9、warning #f6c343、danger #ff6b6b；文字 12px，高度 26px。
- **时间线**：左侧竖线 3px，节点用 12px 圆点，连接线使用 #2b3038；时间戳 12px 字体。
- **图谱/关系视图**：节点使用圆角 16px 卡片，连接线 2px，支持 hover 高亮；证据点可展开小卡片展示 `confidence` / `source` / `status`。
- **Agent Goal 卡片**：目标头部、step rail、thinking/observing 折叠卡片、interrupt 操作区，状态变化必须通过颜色和局部动效表达，不能只依赖文字。

## 9. 设计系统
- **颜色**：
  - 深 mode 主背景 #0d0f14、卡片 #111318、突出色 #5d80ff、内容白 #f5f7ff、次要文本 #9ba3b2。
  - 亮 mode 主背景 #f7f5ef、卡片 #ffffff、突出色 #5d80ff、内容黑 #0c121b、辅助文本 #606775。

- **字体**：主字体建议 `Inter var`，中文 fallback 使用 `Noto Sans SC`；Hero 标题 48px-56px，页面标题 24px-28px，正文字号 16px，辅助 12px。
- **间距**：使用 8px 基数；主要区间 12/16/24/32/48；卡片内 24px padding。
- **圆角**：主卡片/面板 18px，按钮 999px pill，input 12px。
- **阴影**：主工作卡片 `0 30px 60px rgba(0,0,0,0.35)`，浮层 `0 20px 40px rgba(0,0,0,0.45)`。
- **动效**：主交互（按钮、卡片状态）使用 180ms ease-out，面板展开 300ms height transition，状态标签 fade 150ms。
- **暗/亮切换**：保留主色 `#5d80ff`，亮模式将导航换为深灰而不是黑，保持侧边深度感。

## 10. 响应式规则
- `>= 1440px`：使用完整三列布局，左侧导航固定，右侧面板常驻。
- `1200px - 1439px`：保留三列，但右侧面板宽度收缩至 280px，图谱和时间线优先保持主画布宽度。
- `768px - 1199px`：右侧面板改为抽屉或页签式 inspector；底部输入框仍固定，但宽度提升到主列的 92%。
- `< 768px`：左侧导航改为 overlay drawer，右侧策略面板转为 bottom sheet；`Welcome` / `Build` 能力卡片改为单列，`Personal Workspace` / `Runs` 的时间线与详情采用上下堆叠。

## 11. 与 AI Studio 的共通与差异
- 共通点：Dark-first 左侧导航 + 右侧设置面板，卡片浮层，突出按钮组，温度/工具控制面板。
- 差异化：
  - Nasus 的左右结构更显业务分层，主区专注任务与质量画像；AI Studio 更偏 prompt。
  - 在功能配色上引入质量状态色带（success/warning/danger）和时间线信号，以体现治理与风险维度。
  - Nasus 必须紧密表达“Evidence”“Baseline”“Approval”，因此在图谱卡片与控制面板中特别暴露这些信息。
  - 引入“宽屏虚拟控制面板”在 Runs 内显示 Executions，AI Studio 的 Run 面板偏工具。

以上规范可直接供前端设计与开发参考，用于生成 `Welcome`、`Build`、`Dashboard`、`Documentation`、`Project Space`、`Personal Workspace`、`Knowledge`、`Runs`、`Governance` 及其详情态体验。

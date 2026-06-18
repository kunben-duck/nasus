# 前端视觉与交互规范

说明：本文参考 Google AI Studio 的两个关键形态，并将其转译为 Nasus Portal 的视觉与交互基线。本文不是像素级复刻，而是对其工作台气质、信息密度和交互结构的工程化转译。

- `Apps / Build` 形态：参考 2026-06-10 登录后的 `https://aistudio.google.com/apps`，用于指导 Nasus 顶层 `Build / Dashboard / Documentation` 的入口页、创建页和发现页。
- `Playground / Agents` 形态：参考 2026-06-10 登录后的 `https://aistudio.google.com/prompts/new_chat` 中 `Build with Agents` 页面，用于指导 Nasus 的任务模块、`Personal Workspace`、Agent Goal 和执行设置。

硬约束：正式前端实现必须优先对齐 `ux/` 原型和本文的 AI Studio 风格基线；不得回退到普通管理后台风格。

## 0. AI Studio 三图基线

本节固化三张参考图中的关键视觉规则，作为 Nasus Portal 的直接风格基线。后续实现如果与本节冲突，以本节优先。

### 0.1 收起左侧导航

- 左侧导航必须支持 `expanded / collapsed` 两种状态。
- 展开态宽度为 `196px - 220px`，收起态宽度为 `56px - 64px`；收起后主画布要自然扩展，不能留下空白侧栏。
- 收起态只保留品牌图标、一级导航图标、底部工具图标和账号头像；隐藏品牌文字、分组标题、导航 label、升级/状态卡正文。
- 收起态的当前页面选中态仍然是低对比圆角 pill，不改成高亮色块。选中项尺寸建议 `36px x 32px`，图标居中。
- 收起/展开按钮为 `32px` 圆形或圆角方形按钮，位于左栏右上侧靠近分割线的位置；按钮本身不改变主内容层级。
- 收起动画使用 `180ms - 220ms ease-out`，只改变 width、opacity 和 transform，不触发布局闪烁。
- 收起态导航项 hover 必须显示 tooltip，tooltip 使用暗色浮层、12px 字号、6px-8px 内边距，不影响布局。
- 底部工具区在收起态从横排按钮变为竖向图标列；设置、通知、搜索、模型/API key 入口仍可直接访问。
- 在 `< 768px` 窄屏下，左侧导航不使用收起态，而改为 overlay drawer。

### 0.2 设置按钮与设置菜单

- 顶层页面采用 AI Studio 式设置入口：左栏底部工具区有 `Settings` 图标按钮，顶层画布右上也可保留一个 `40px` 浮动设置按钮作为快捷入口。
- 设置菜单必须是 overlay popover，不占据文档流，不推动主画布、不造成整体配置框上浮。
- 一级菜单宽度建议 `220px - 248px`，圆角 `10px - 12px`，背景 `#1f1f1f`，边框 `1px solid rgba(255,255,255,0.08)`，阴影 `0 18px 48px rgba(0,0,0,0.45)`。
- 菜单项高度 `38px - 42px`，左侧线性图标使用 `18px / wght 300 / opsz 30`，中间 label，右侧 chevron 或当前值；hover 背景 `#333333`，文字从 `#c7c7c7` 提升到 `#f1f3f4`。
- 二级菜单必须由用户点击一级菜单项后在右侧展开；一级菜单本身只展示 `Theme / Language / Model configuration / Notifications / Status` 等入口，不能把所有选项直接平铺在同一页。
- 二级菜单优先向右展开；如果右侧空间不足或内容过长，则用同尺寸 overlay 替换一级菜单，并提供顶部返回行，不能强行向下叠加导致弹层溢出。
- 二级菜单最大高度为 `min(560px, calc(100vh - 48px))`，超出后菜单内部滚动，页面本身不滚动。
- `Theme` 二级菜单必须包含 `Light / Dark / System` 三项；`Language` 包含 `English / 中文`；`Model configuration` 必须包含 `LLM / Embedding / Rerank` 三个 route tab，每个 tab 内包含 `System default / Custom provider`、Provider、Base URL、Model、API key、当前 live/fallback 状态和 `Test connection`。
- 高风险或敏感配置，例如自定义 API key、模型 Provider、Embedding/Rerank adapter、通知权限，必须在菜单内显示状态说明，不用 toast 代替状态。
- 设置菜单关闭规则：点击外部关闭，`Esc` 关闭，提交后回到上一级菜单；不得清空用户已输入但未保存的配置草稿。

### 0.3 主页对话页面样式

- `Build` 首页必须采用 AI Studio Apps 的中心对话生成器结构，而不是大块后台卡片区。
- 首屏核心结构固定为：左侧导航、中心 Hero 标题、居中大输入卡、输入卡下方横向能力 chip row、下半屏轻量 discover/project 模块。
- Hero 标题使用 `Build quality projects with Nasus`，其中 `Nasus` 首字母大写；标题必须与输入卡共享同一中心轴，不能相对输入卡偏左或偏右。
- 首屏中心组的垂直位置应接近画布中线略上，推荐中心点落在主画布高度的 `42% - 48%`；不得贴近顶部，也不得压到下半屏卡片。
- 大输入卡宽度 `760px - 840px`，空态高度 `104px - 120px`，有选中技能卡时可扩展到 `160px - 188px`；不能因为技能卡过多让输入区变成笨重表单。
- 输入卡使用深色表面和 1px 彩色流动边框，颜色顺序为蓝、绿、黄、红/粉的低饱和渐变；禁止使用单一绿色基底或大片绿色光晕。
- 输入卡内部第一行是文本输入区域，placeholder 使用 12px-13px、`#9aa0a6`；输入文本使用 13px-14px、`#e8eaed`，行高不低于 1.45。
- `I guess you` 是智能推荐按钮，样式为中性暗色 pill + 蓝色 sparkle 图标；它的职责是推荐技能组合并生成提示词，不是提交按钮。
- `Build` 提交按钮只在输入框已有提示词或用户选择了有效技能组合后出现；样式应比 `I guess you` 更强，使用实心深灰/蓝灰 pill，右侧可带 return icon。
- 能力 chip row 放在输入卡下方 `14px - 18px`，每个 chip 宽度由内容决定，不强制拉宽；图标与文字对齐到 16px 图标网格。
- 首屏下方的 discover/project 模块必须视觉降级，不能与主输入卡抢焦点。它可以在首屏底部露出标题与少量卡片，但不应成为首屏主体。

## 1. 视觉方向
- 以 Google AI Studio 的沉稳暗色工作台为参考：深灰背景、低对比边框、分层卡片、左侧导航、中心大画布、浮动设置入口和必要时出现的右侧设置面板。避免过度鲜艳配色，突出内容中心区的微光聚焦。
- 顶层入口页采用 `Apps / Build` 风格：左侧分组导航固定，主区居中构图，大标题 + 大输入卡 + 横向 chip row + 模板/项目卡片区。页面空态要有明确创作冲动，而不是后台列表。
- 任务模块采用 `Playground / Agents` 风格：左侧项目导航固定，中间是 Agent/Task 模板卡片网格与底部固定 composer，右侧是 `Run settings` 风格的策略、工具、环境和证据控制面板。
- 将视觉语义分为三类：`探索`（Welcome / Build / Dashboard / Documentation）、`工作`（Project Space / Personal Workspace / Runs / Knowledge）、`治理`（Governance / Approval / Release Readiness）。每类保持一致的色调与动效节奏。
- 除暗模式，还需提供亮模式。亮模式使用米色、浅灰背景，保留相同层级关系（导航暗、主体亮、控制面板暗）以防干扰。

## 2. 布局框架
- 采用两种布局模式：
  - `Top-level Build Layout`：`左侧导航`（展开 196px-220px，收起 56px-64px）+ `中间大画布`（居中最大宽度 920px-1080px）+ `浮动设置按钮`。顶层 `Build / Dashboard / Documentation` 默认不放常驻右栏。
  - `Workspace Layout`：`左侧项目导航`（220px-232px 固定）+ `中间主工作区`（自动拉伸）+ `右侧 inspector`（300px-320px 固定）。进入具体项目、US、运行和审批详情后使用。
- `Personal Workspace / Task Workspace` 采用 AI Studio Agents 的比例：左侧导航 196px-220px，中间任务画布最小 760px，右侧 `Run settings` 面板 300px-320px，底部 composer 横跨中间画布但不覆盖右侧面板。
- 顶部不设全局浮动 header，采用左侧导航作为全局入口；主工作区内部使用“局部标题栏 + 内容画布”的壳层结构。
- `Welcome` / `Build` 页面保留 AI Studio Apps 风格的大面积留白：中心是单句 Hero 标题和大输入卡，下面是横向建议 chip，底部或下半屏是模板/最近项目卡片。`Dashboard` 和 `Documentation` 共用同一顶层壳层，但内容更偏项目组合和文档发现。
- 行动按钮组、图谱、时间线、证据卡片等均在主工作区内组织，使用 12px/16px/24px/32px 间距系统，不做满屏瀑布流。

## 3. 实际参考页面结构
- 左侧导航分为四段：品牌区、分组导航区、升级/提示卡、底部工具与账户区。分组标题使用 11px-12px uppercase，导航项使用 14px 中灰，选中态是低对比 pill，不是强色块。
- `Apps / Build` 主工作区以“中心生成器”组织：Hero 标题居中，大输入卡居中，输入卡下方是横向 chip row，继续向下才是 discover/remix 卡片区。Nasus 的 `Build` 对应“创建项目与初始化系统画像生成器”。
- 输入卡是页面视觉核心：高度约 120px-132px，宽度约 760px-840px，圆角 20px-24px，暗色表面，边框带细微绿/蓝/橙渐变光，不使用厚重阴影。
- chip row 是横向滚动的快捷能力入口：每个 chip 高度约 34px，圆角 999px，背景略高于页面底色，左侧可带小图标，支持 hover 亮度提升。
- 设置入口在顶层页可作为右上浮动圆形按钮；只有进入项目工作区后才展开常驻右侧 inspector。
- 底部输入框不是简单表单，而是主工作触发器。它需要支持文本输入、工具按钮、上下文 chip、附加材料和主操作按钮组合。
- `Playground / Agents` 主工作区以“任务模板 + 执行设置”组织：标题区显示当前空间名，主标题为任务目标或 `Build with Agents` 类文案，右上提供 `Models / Agents` 或 `Tasks / Agents` segmented control，中间展示 2-3 列任务模板卡片，底部固定 composer 挂载 tools chips。

## 4. 导航与侧栏
- 左侧导航采用“品牌 + 分组文本导航”为主，不是只放图标。背景色 #111318，左栏与主画布之间使用 1px #25272d 分割线。
- 左侧导航必须支持收起态。收起态不是移动端抽屉，而是桌面端 compact rail；只隐藏文字，不改变导航结构和当前路由。
- 顶层分组建议映射为：
  - `EXPLORE`：`Welcome`、`Recent Sessions`
  - `BUILD`：`New Project`、`My Projects`
  - `MANAGE`：`Dashboard`、`Documentation`
- `New Project` / `Build` 选中态采用 30px-32px 高度 pill，背景 #2a2a2a，文字 #e5e7eb，左侧线性图标使用 `18px / wght 300 / opsz 30`。
- 每个导航项支持 badge（状态/未读）与 mini-progress（任务收敛率），使用 14px 字体、70% 透明度；底部工具入口与主导航视觉上分组。
- 顶部品牌区保留系统名称、当前空间或版本切换；底部显示用户头像、设置与辅助入口；提供通知、设置、搜索、模型/API key 等 AI Studio 风格图标按钮。
- 左栏底部可放一张低调 upgrade/status 卡。Nasus 中这张卡不做商业升级文案，而显示“System image health / Model provider status / Project quota”等运行状态。

## 5. 主工作区（Welcome / Build / Dashboard / Project Space）
- 背景采用 #111111-#151515 的低对比暗色，顶层页面主区不使用强卡片铺满，而是让中心输入卡成为焦点。
- 卡片采用圆角 18px，内边距 24px，卡片之间垂直间距 16px，卡片顶部可插入水平步骤条或状态条。
- `Welcome` / `Build` 的 Hero 标题采用 AI Studio Apps 的轻量大标题风格：36px-42px、font-weight 400、letter-spacing -0.02em，文字 #e8eaed，不使用粗黑大标题。
- `Build` 首屏固定结构：居中 Hero、`Project Creation Composer` 大输入卡、能力 chip row、Draft Projects / Templates 卡片区。创建项目、导入 Git、导入 US 文档、导入 UX、初始化系统画像都从同一 composer 和工具 chip 触发。
- `Dashboard` 使用同一壳层语言，但主区从“生成器”转为“组合态”：Hero query composer + 项目卡片网格 + 风险/阻塞摘要。不要做传统 BI 大屏。
- `Personal Workspace` 采用 AI Studio Agents 风格的任务工作台：上方是 US/Task 标题和 `Tasks / Agents` 模式切换，中间先展示任务模板卡片或当前 AgentGoal 运行卡，下面进入对话与质量资产画布，底部固定 composer 用于继续任务、补充上下文、请求重新生成。
- `Knowledge` 使用“图谱/列表 + 对象详情 + 证据细节”的双层结构；`Runs` 使用“运行列表/时间线 + 运行详情 + 右侧过滤/放行”结构；`Governance` 使用“列表 + diff/detail + 放行面板”结构。

## 6. 右侧控制面板
- 顶层 `Build / Dashboard / Documentation` 默认不展示常驻右栏；只保留右上角 40px 浮动设置按钮和必要时打开的 overlay rail。
- 设置入口默认以 overlay popover 呈现，不能把右侧控制面板当作设置页直接常驻打开；复杂设置才进入独立 modal 或 setting route。
- 控制面板背景 #14181f，具备 2px 内边距的 separator 线，线条使用 30% 亮度。
- 分节标题 12px 大写；每节下方放置 toggle/checkbox/slider/select 控件，控件颜色使用 #5d80ff。
- 面板应采用“卡片堆叠”而不是长表单直排。每张卡片可以是策略摘要、参数设置、证据池、审批动作、环境快照。
- 控件包括：策略切换（toggle）、证据筛选（multi-select pill）、运行级别（tab）、温度/推理强度 slider、上下文范围选择、执行开关、审批说明输入。
- `Personal Workspace` 右侧面板要借鉴 AI Studio 的 `Run settings`：顶部显示当前 Agent/Task Profile 卡片；下方是 `System instructions`、`Tools`、`Environment`、`Sources`、`Network / Policy` 等折叠分组。Nasus 中对应为质量策略、工具开关、执行环境、证据来源和审批策略。
- 控制面板提供“证据池”“策略快照”“人工 override”区域，默认折叠，可展开。
- 右侧面板 tab 不是全局固定值。至少要支持：
  - `Welcome`：`Activity / Tips / Status`
  - `Build`：`Projects / Imports / Health`
  - `Dashboard`：`Alerts / Progress / Activity`
  - `Documentation`：`Topics / Templates / Updates`
  - `Personal Workspace`：`Profile / Tools / Environment / Evidence / Policy`
  - `Knowledge Gallery`：`Graph / Objects / Search`
  - `Runs`：`Active / History / Failed`
  - `Governance`：`Pending / Resolved / Policy`

## 7. 底部输入框与操作区
- 顶层 `Build` 的输入框不是底部固定，而是首屏居中大输入卡；项目工作区和会话型页面再使用底部固定 composer。
- 顶层输入卡宽度建议 760px-840px，高度 120px-132px，最大不超过主列宽度的 78%；项目工作区底部输入框宽度建议 720px-960px，最大不超过主列宽度的 82%。
- 输入框容器使用深色卡片式浮层，内部支持文本输入、多行扩展、工具按钮、上下文 chip、上传入口和主提交按钮。顶层输入卡右侧放 `I guess you` 智能推荐按钮；其作用是推荐用户选择技能卡片并自动生成提示词。`Build` 主按钮必须在有提示词或有效技能选择后才出现。
- 输入框前置按钮用于“工具/附加材料/引用上下文”，后置按钮用于“发起分析/继续执行/申请审批”；不同页面沿用同一组件骨架。
- `Build` 页面中输入框承担“开始一个项目创建任务”；`Dashboard` 页面中承担“询问组合进展与风险”；`Personal Workspace` 页面中承担“补充上下文并请求下一步动作”；`Runs` 页面中承担“请求归因/重跑/提交放行”的快捷动作。
- `Personal Workspace` 的 composer 必须支持工具 chip 固定在输入区底部，例如 `Tools`、`Generate scenarios`、`Code execution`、`Evidence sources`、`Release gate`。被启用的 chip 使用蓝灰底色并带关闭按钮，行为参考 AI Studio Agents 的工具 chip。

## 8. 组件规范
- **顶层输入卡**：背景 #1d1d1d，圆角 22px，border 1px solid rgba(255,255,255,0.05)，外层使用 `linear-gradient(90deg, rgba(52,168,83,.55), rgba(251,188,5,.35), rgba(66,133,244,.45))` 形成 1px 微光边框。
- **侧栏收起按钮**：32px 圆形或圆角方形，背景 #2a2a2a，hover #333333，线性图标使用 `18px / wght 300 / opsz 30`；位置固定在左栏右上侧，不随滚动移动。
- **线性图标风格**：所有侧栏、工具栏、菜单和 composer 中的线性功能图标统一采用 AI Studio / Material Symbols Outlined 视觉语言。默认使用 `Material Symbols Outlined` 或等价线性图标库，图标语义名直接映射为 `notifications / settings / search / key / upload / add / close` 等，不再手写比例不稳定的 SVG 路径。
- **线性图标参数**：图标尺寸默认 `18px x 18px`，`font-variation-settings: 'FILL' 0, 'GRAD' 0, 'opsz' 30, 'wght' 300`，颜色默认 `rgb(140,140,140)` / `#8c8c8c`；hover 可提升到 `#e3e3e3`。如果使用 SVG 替代，必须匹配同等视觉重量：线宽约 `1.5px - 1.75px`，端点圆角，viewBox 居中，禁止使用粗填充或不等比例路径。
- **左栏底部工具按钮**：通知、设置、搜索、模型/API key 入口固定使用 AI Studio 底部工具栏尺度：外层 `icon-box` 为 `45px x 32px`，背景透明，`border: 1px solid rgb(38,38,38)`，圆角 `8px`；内部触发区域约 `43px x 30px`，图标 `18px` 居中；按钮之间横向间距约 `8px`。边框必须保留，但只能是低对比细边框，禁止使用厚边框、实底方块或高亮描边。
- **设置菜单**：overlay popover，宽 220px-248px，圆角 10px-12px，菜单项高 38px-42px；二级菜单向右展开或原位替换，不允许把主界面向上/向下挤压。
- **`I guess you` 按钮**：高度 32px-34px，圆角 999px，背景 #303134，文字 #e8eaed，左侧 14px-16px 蓝色 sparkle 图标；hover 背景 #3a3b3d。
- **`Build` 按钮**：高度 32px-34px，圆角 999px，背景 #3b4354 或 #343a46，文字 #f1f3f4；仅在输入有效时出现，disabled 态不可见或透明度低于 0.38。
- **顶层 chip**：高度 34px，圆角 999px，背景 #252525，hover #303030，文字 13px-14px，图标 16px。
- **任务模板卡片**：2-3 列网格，卡片背景 #1d1d1d，圆角 12px-14px，padding 16px，图标块 28px，标题 14px semibold，描述 13px / line-height 1.45，hover 时边框从透明变为 rgba(255,255,255,0.12)。
- **任务模式切换**：`Tasks / Agents` segmented control，高度 36px，背景 #1e1e1e，选中态 #2b2b2b，圆角 999px，文字 12px-13px。
- **工具 chip in composer**：高度 34px，圆角 10px-16px，默认 #2a2a2a，启用态 #36405a，文字 #d7defa，右侧 close icon 14px。
- **卡片**：背景 #1a1d24，圆角 18px，阴影 0 20px 40px rgba(0,0,0,0.25)，border 1px solid rgba(255,255,255,0.04)。
- **列表**：条目间隔 12px，hover 使用 #20252c 背景；左侧显示状态色带（5px），根据状态使用成功/警告/中性色。
- **表单**：输入框背景 #0f1016，边框 1px solid rgba(255,255,255,0.1)，输入文字 16px，placeholder 60% 透明度；聚焦时边框与阴影加强。
- **状态标签**：使用 pill 样式，success #38d9a9、warning #f6c343、danger #ff6b6b；文字 12px，高度 26px。
- **时间线**：左侧竖线 3px，节点用 12px 圆点，连接线使用 #2b3038；时间戳 12px 字体。
- **图谱/关系视图**：节点使用圆角 16px 卡片，连接线 2px，支持 hover 高亮；证据点可展开小卡片展示 `confidence` / `source` / `status`。
- **Agent Goal 卡片**：目标头部、step rail、thinking/observing 折叠卡片、interrupt 操作区，状态变化必须通过颜色和局部动效表达，不能只依赖文字。
- **Run Settings 面板**：分组标题 13px semibold，说明文字 12px，toggle 高度 22px，分组之间使用 1px rgba(255,255,255,0.06) 分割；危险或高成本工具必须显示成本/风险提示。

## 9. 设计系统
- **颜色**：
  - 深 mode 主背景 #111111、侧栏 #151515、卡片 #1d1d1d、hover #2a2a2a、突出色 #8ab4f8 / #34a853、内容白 #e8eaed、次要文本 #9aa0a6。
  - 亮 mode 主背景 #f7f5ef、卡片 #ffffff、突出色 #5d80ff、内容黑 #0c121b、辅助文本 #606775。

- **字体**：主字体建议 `Google Sans Text` 风格的近似组合：`Inter var` / `Noto Sans SC`。Hero 标题 36px-42px、font-weight 400；页面标题 24px-28px；正文字号 14px-16px；辅助 11px-12px。
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
- 共通点：Dark-first 左侧分组导航、中心大画布、低对比 pill 选中态、大输入卡、横向 chip row、浮动设置入口、卡片浮层。
- 任务模块共通点：模板卡片网格、`Tasks / Agents` segmented control、底部固定 composer、工具 chips、右侧 `Run settings` 式控制面板。
- 差异化：
  - Nasus 的顶层 Build 不生成 App，而是创建项目、导入材料并初始化系统画像。
  - Nasus 进入项目后比 AI Studio 更强调右侧 inspector，主区专注任务与质量画像；AI Studio 更偏 prompt/app 生成。
  - 在功能配色上引入质量状态色带（success/warning/danger）和时间线信号，以体现治理与风险维度。
  - Nasus 必须紧密表达“Evidence”“Baseline”“Approval”，因此在图谱卡片与控制面板中特别暴露这些信息。
  - 引入“宽屏虚拟控制面板”在 Runs 内显示 Executions，AI Studio 的 Run 面板偏工具。

以上规范可直接供前端设计与开发参考，用于生成 `Welcome`、`Build`、`Dashboard`、`Documentation`、`Project Space`、`Personal Workspace`、`Knowledge`、`Runs`、`Governance` 及其详情态体验。

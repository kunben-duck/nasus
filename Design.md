# AutoTest AI - 智能自动化测试平台 Design Specification

## 1. Overview

### 1.1 Project Summary
AutoTest AI 是一个智能自动化测试平台，通过 AI 技术实现从用户故事到自动化测试脚本的完整链路。平台支持 US 需求管理、AI 智能解析、测试用例自动生成、自动化脚本创建、执行监控和报告分析等全流程功能。

### 1.2 Target Audience
- 软件测试工程师
- QA 团队负责人
- 产品经理
- 开发工程师
- DevOps 工程师

### 1.3 Language
- 所有 UI 文本使用简体中文
- 代码注释使用英文

### 1.4 Website Type
- 单页应用 (SPA) 风格的仪表盘系统
- 深色科技主题
- 数据密集型管理界面

---

## 2. Page Manifest (CRITICAL)

| Page ID | Page Name | File Name | Is Entry | SubAgent Notes |
|---------|-----------|-----------|----------|----------------|
| index | 仪表盘 Dashboard | index.html | YES | 项目概览、执行统计、最近活动、快速入口 |
| us-management | US需求管理 | us-management.html | NO | US列表、导入功能、AI解析状态、验证点展示 |
| test-cases | 测试用例管理 | test-cases.html | NO | 用例列表、生成状态、优先级标签、关联US |
| script-studio | 脚本工作室 | script-studio.html | NO | 可视化编辑器、代码编辑器、元素选择器、Midscene风格 |
| execution-hub | 执行中心 | execution-hub.html | NO | 执行控制、实时监控、瀑布图、执行日志 |
| reports | 报告中心 | reports.html | NO | 历史报告、截图查看、录屏回放 |
| settings | 系统设置 | settings.html | NO | 配置表单、集成设置、用户管理、API密钥 |

---

## 3. Global Design System

### 3.1 Color Palette

#### Primary Colors
| Name | Hex | Usage |
|------|-----|-------|
| --color-bg-primary | #0a0a0f | 主背景色，深邃黑色 |
| --color-bg-secondary | #12121a | 次级背景，卡片背景 |
| --color-bg-tertiary | #1a1a25 | 三级背景，hover状态 |
| --color-bg-elevated | #222230 |  elevated表面，输入框背景 |

#### Accent Colors
| Name | Hex | Usage |
|------|-----|-------|
| --color-accent-cyan | #00d4ff | 主强调色，霓虹青色 |
| --color-accent-purple | #7c3aed | 次强调色，霓虹紫色 |
| --color-accent-blue | #3b82f6 | 蓝色强调，信息提示 |
| --color-accent-green | #10b981 | 成功状态，通过标识 |
| --color-accent-yellow | #f59e0b | 警告状态，待处理 |
| --color-accent-red | #ef4444 | 错误状态，失败标识 |

#### Gradient Definitions
```css
--gradient-primary: linear-gradient(135deg, #00d4ff 0%, #7c3aed 100%);
--gradient-glow: linear-gradient(180deg, rgba(0, 212, 255, 0.15) 0%, transparent 100%);
--gradient-card: linear-gradient(145deg, rgba(18, 18, 26, 0.9) 0%, rgba(10, 10, 15, 0.95) 100%);
--gradient-border: linear-gradient(90deg, #00d4ff, #7c3aed, #00d4ff);
```

#### Text Colors
| Name | Hex | Usage |
|------|-----|-------|
| --color-text-primary | #ffffff | 主要文本 |
| --color-text-secondary | #a1a1aa | 次要文本，描述 |
| --color-text-muted | #71717a | 弱化文本，占位符 |
| --color-text-accent | #00d4ff | 强调文本 |

#### Glassmorphism
```css
--glass-bg: rgba(18, 18, 26, 0.7);
--glass-border: rgba(255, 255, 255, 0.08);
--glass-blur: blur(20px);
--glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
```

### 3.2 Typography

#### Font Family
```css
--font-primary: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

#### Font Sizes
| Name | Size | Line Height | Usage |
|------|------|-------------|-------|
| --text-xs | 0.75rem (12px) | 1rem | 标签、徽章 |
| --text-sm | 0.875rem (14px) | 1.25rem | 次要文本 |
| --text-base | 1rem (16px) | 1.5rem | 正文 |
| --text-lg | 1.125rem (18px) | 1.75rem | 小标题 |
| --text-xl | 1.25rem (20px) | 1.75rem | 卡片标题 |
| --text-2xl | 1.5rem (24px) | 2rem | 区块标题 |
| --text-3xl | 1.875rem (30px) | 2.25rem | 页面标题 |
| --text-4xl | 2.25rem (36px) | 2.5rem | 大标题 |
| --text-5xl | 3rem (48px) | 1 | 英雄标题 |

#### Font Weights
| Name | Weight | Usage |
|------|--------|-------|
| --font-normal | 400 | 正文 |
| --font-medium | 500 | 按钮、标签 |
| --font-semibold | 600 | 标题、强调 |
| --font-bold | 700 | 大标题 |

### 3.3 Spacing System

| Name | Value | Usage |
|------|-------|-------|
| --space-1 | 0.25rem (4px) | 极小间距 |
| --space-2 | 0.5rem (8px) | 紧凑间距 |
| --space-3 | 0.75rem (12px) | 小间距 |
| --space-4 | 1rem (16px) | 标准间距 |
| --space-5 | 1.25rem (20px) | 中等间距 |
| --space-6 | 1.5rem (24px) | 大间距 |
| --space-8 | 2rem (32px) | 区块内边距 |
| --space-10 | 2.5rem (40px) | 大区块间距 |
| --space-12 | 3rem (48px) | 页面内边距 |
| --space-16 | 4rem (64px) | 大区块间距 |

### 3.4 Border Radius

| Name | Value | Usage |
|------|-------|-------|
| --radius-sm | 0.25rem (4px) | 小元素 |
| --radius-md | 0.5rem (8px) | 按钮、输入框 |
| --radius-lg | 0.75rem (12px) | 卡片 |
| --radius-xl | 1rem (16px) | 大卡片、模态框 |
| --radius-2xl | 1.5rem (24px) | 特殊卡片 |
| --radius-full | 9999px | 圆形元素 |

### 3.5 Shadows

```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
--shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
--shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
--shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.6);
--shadow-glow-cyan: 0 0 20px rgba(0, 212, 255, 0.3);
--shadow-glow-purple: 0 0 20px rgba(124, 58, 237, 0.3);
--shadow-inner: inset 0 2px 4px rgba(0, 0, 0, 0.3);
```

### 3.6 Animation Specifications

#### Timing Functions
```css
--ease-default: cubic-bezier(0.4, 0, 0.2, 1);
--ease-in: cubic-bezier(0.4, 0, 1, 1);
--ease-out: cubic-bezier(0, 0, 0.2, 1);
--ease-bounce: cubic-bezier(0.68, -0.55, 0.265, 1.55);
--ease-spring: cubic-bezier(0.175, 0.885, 0.32, 1.275);
```

#### Duration Values
| Name | Value | Usage |
|------|-------|-------|
| --duration-fast | 150ms | 微交互 |
| --duration-normal | 300ms | 标准过渡 |
| --duration-slow | 500ms | 复杂动画 |
| --duration-slower | 700ms | 页面过渡 |

#### Animation Presets
```css
/* Fade In Up */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
--animate-fade-in-up: fadeInUp 0.5s var(--ease-out) forwards;

/* Fade In Scale */
@keyframes fadeInScale {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
--animate-fade-in-scale: fadeInScale 0.4s var(--ease-out) forwards;

/* Slide In Right */
@keyframes slideInRight {
  from { opacity: 0; transform: translateX(30px); }
  to { opacity: 1; transform: translateX(0); }
}
--animate-slide-in-right: slideInRight 0.5s var(--ease-out) forwards;

/* Pulse Glow */
@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 5px rgba(0, 212, 255, 0.5); }
  50% { box-shadow: 0 0 20px rgba(0, 212, 255, 0.8), 0 0 40px rgba(0, 212, 255, 0.4); }
}
--animate-pulse-glow: pulseGlow 2s ease-in-out infinite;

/* Shimmer */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
--animate-shimmer: shimmer 2s linear infinite;

/* Float */
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}
--animate-float: float 3s ease-in-out infinite;

/* Spin Slow */
@keyframes spinSlow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
--animate-spin-slow: spinSlow 8s linear infinite;

/* Border Flow */
@keyframes borderFlow {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
--animate-border-flow: borderFlow 3s ease infinite;
```

### 3.7 3D Background System

#### Particle Configuration
```javascript
const particleConfig = {
  count: 80,
  color: '#00d4ff',
  secondaryColor: '#7c3aed',
  size: { min: 1, max: 3 },
  speed: { min: 0.2, max: 0.8 },
  opacity: { min: 0.3, max: 0.8 },
  connectionDistance: 150,
  connectionOpacity: 0.15,
  mouseRadius: 200,
  mouseForce: 0.02
};
```

#### Grid Floor Effect
```css
.grid-floor {
  background-image: 
    linear-gradient(rgba(0, 212, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 212, 255, 0.03) 1px, transparent 1px);
  background-size: 50px 50px;
  transform: perspective(500px) rotateX(60deg);
  transform-origin: center top;
}
```

---

## 4. Page Specifications

### 4.1 Index Page (Dashboard - Entry Point)

#### Layout Structure
```
Sidebar (240px) | Main Content
- Logo          | Header (64px)
- Navigation    | Stats Cards (4 cols)
- Dashboard     | Charts Row (2 cols)
- US Mgmt       | Activity | Quick Actions
- Test Cases    |
- Script Studio |
- Execution Hub |
- Reports       |
- Settings      |
```

#### Sections Detail

**Header Section**
- Height: 64px
- Background: transparent
- Left: Page title "仪表盘" + breadcrumb
- Right: Search icon, Notification bell (with badge), User avatar dropdown
- Border-bottom: 1px solid rgba(255,255,255,0.05)

**Stats Cards Row**
- 4-column grid, gap: 24px
- Each card:
  - Height: 120px
  - Background: var(--glass-bg)
  - Border: 1px solid var(--glass-border)
  - Border-radius: var(--radius-lg)
  - Padding: 24px
  - Backdrop-filter: var(--glass-blur)

Cards content:
1. **项目总数**: Icon (Folder), Number, Trend indicator
2. **测试用例**: Icon (FileCheck), Number, +X this week
3. **执行次数**: Icon (Play), Number, Success rate
4. **通过率**: Icon (TrendingUp), Percentage, Chart mini

**Charts Row**
- 2-column grid (60% / 40%), gap: 24px
- Left: **执行趋势图** (Area Chart)
  - Height: 320px
  - Shows last 30 days execution data
  - Gradient fill under line
- Right: **状态分布图** (Donut Chart)
  - Height: 320px
  - Pass/Fail/Running/Pending segments
  - Center shows total count

**Bottom Row**
- 2-column grid (65% / 35%), gap: 24px
- Left: **最近活动** (Activity Feed)
  - Height: 400px
  - Scrollable list
  - Each item: Icon + Description + Timestamp
- Right: **快速操作** (Quick Actions)
  - Height: 400px
  - 4 action buttons in 2x2 grid
  - Each: Icon + Label + Description

#### Animations
- Page load: Cards fade in with stagger (100ms delay each)
- Stats numbers: Count up animation (1.5s duration)
- Charts: Draw animation on load (1s duration)
- Hover on cards: Scale 1.02, glow shadow

---

### 4.2 US Management Page

#### Layout Structure
- Header + Action Bar
- Filter Bar
- US List (Table/Card View toggle)
- Pagination

#### Sections Detail

**Action Bar**
- Left: Page title "US 需求管理" + count badge
- Right buttons:
  - "导入 US" (secondary button with Upload icon)
  - "新建 US" (primary button with Plus icon)

**Filter Bar**
- Height: 56px
- Elements:
  - Search input (placeholder: "搜索 US 编号或标题...")
  - Status dropdown: 全部状态 | 待解析 | 解析中 | 已完成 | 失败
  - Project dropdown
  - Date range picker
  - View toggle: Table | Card

**US List - Table View**
- Columns:
  1. Checkbox (select all)
  2. US 编号 (e.g., US-1234) - cyan color, monospace
  3. 标题 - truncate at 200px
  4. 所属项目 - badge
  5. 验证点数量 - number with icon
  6. 用例数量 - number with icon
  7. 状态 - colored badge
  8. 更新时间 - relative time
  9. 操作 - dropdown menu

**Status Badges**
- 待解析: gray bg, clock icon
- 解析中: blue bg with pulse animation, loader icon
- 已完成: green bg, check icon
- 失败: red bg, alert icon

**AI Parse Modal**
- Width: 600px
- Title: "AI 解析 US"
- Content:
  - US 内容 textarea (min 200px)
  - Or: "从 JIRA 导入" button
  - Parse options checkboxes
  - "开始解析" primary button
- Progress indicator during parsing

#### Animations
- Table rows: stagger fade in (50ms delay)
- Status badges: pulse for "解析中" state
- Modal: scale in from center (0.3s)
- Cards: lift on hover (translateY -4px)

---

### 4.3 Test Cases Page

#### Layout Structure
- Header + Action Bar
- Filter & Bulk Actions
- Test Case List (expandable cards)
- Pagination

#### Sections Detail

**Action Bar**
- Left: "测试用例" + count
- Right:
  - "批量生成脚本" button
  - "生成用例" dropdown (从US/从验证点/手动)

**Filter Bar**
- Search: "搜索用例标题、步骤..."
- Priority filter: P0 | P1 | P2 | P3
- Status filter: 草稿 | 已评审 | 已归档
- Type filter: 功能 | 性能 | 安全 | 兼容
- Tags filter: multi-select

**Test Case Card**
- Full width, expandable
- Header (always visible):
  - Checkbox
  - Priority badge (P0=red, P1=orange, P2=yellow, P3=green)
  - Title
  - Tags (max 3 visible)
  - Linked US (clickable)
  - Status badge
  - Expand icon
- Expanded content:
  - 前置条件
  - 测试步骤 (numbered list)
  - 预期结果
  - 关联验证点
  - 操作按钮: 编辑 | 生成脚本 | 删除

**Priority Badges**
- P0: bg-red-500/20, text-red-400, border-red-500/30
- P1: bg-orange-500/20, text-orange-400
- P2: bg-yellow-500/20, text-yellow-400
- P3: bg-green-500/20, text-green-400

**Generate Script Modal**
- Width: 500px
- Title: "生成自动化脚本"
- Content:
  - Selected test case(s) list
  - Target framework: Playwright / Cypress / Selenium
  - Options: Add comments | Include waits | Page object mode
  - "生成" button with loading state

#### Animations
- Cards: smooth expand/collapse (0.3s)
- Priority badges: subtle glow on hover
- Generate button: loading spinner animation

---

### 4.4 Script Studio Page

#### Layout Structure
- Header + Toolbar
- Editor Area (split view 50/50)
  - Visual Canvas (left)
  - Code Editor (right)
- Properties Panel (collapsible, 280px)

#### Sections Detail

**Toolbar**
- Left:
  - Script name input (editable)
  - "保存" button
  - "运行" primary button with play icon
- Right:
  - Undo/Redo buttons
  - Zoom controls (for visual canvas)
  - View toggle: Split | Visual Only | Code Only

**Visual Canvas (Midscene.js Style)**
- Background: dark grid pattern
- Features:
  - Drag & drop action blocks
  - Connection lines between actions
  - Mini-map in corner
  - Zoom: 50% - 200%

**Action Blocks**
Types of blocks:
1. **Navigate**: url input, icon: Globe
2. **Click**: element selector, icon: MousePointer
3. **Type**: selector + text input, icon: Keyboard
4. **Wait**: condition selector, icon: Clock
5. **Assert**: assertion type + expected, icon: CheckSquare
6. **Screenshot**: name input, icon: Camera
7. **Hover**: element selector, icon: Move
8. **Scroll**: direction + amount, icon: ArrowDown

Block styling:
- Width: 200px
- Height: auto (min 60px)
- Border-radius: 8px
- Header: icon + action type
- Body: configurable inputs
- Connection ports: top (in), bottom (out)
- Selected: cyan border glow

**Code Editor**
- Monaco Editor or CodeMirror
- Theme: dark, matching platform
- Syntax highlighting for TypeScript/JavaScript
- Line numbers
- Minimap disabled
- Font: JetBrains Mono, 14px

**Properties Panel**
- Collapsible, width: 280px
- Sections:
  - 元素选择器 (Element selector)
  - 动作配置 (Action configuration)
  - 高级选项 (Advanced options)

#### Animations
- Block drag: smooth follow with shadow
- Connection lines: animated dash flow
- Block add: scale in animation
- Code sync: highlight changed lines

---

### 4.5 Execution Hub Page

#### Layout Structure
- Header + Run Controls
- Execution Status Bar
- Waterfall Chart
- Live Log | Screenshots (split view)

#### Sections Detail

**Run Controls**
- Left: "执行中心"
- Center: Environment selector (dev/staging/prod)
- Right:
  - "选择脚本" dropdown
  - "开始执行" primary large button (green when idle, pulse when running)
  - "停止" button (red, visible when running)

**Execution Status Bar**
- Height: 80px
- 5 status indicators:
  1. 排队中 - gray/blue
  2. 初始化 - blue
  3. 执行中 - cyan with pulse
  4. 生成报告 - yellow
  5. 完成 - green
- Progress bar connecting all
- Current step highlighted

**Waterfall Chart**
- Full width, height: 400px
- X-axis: Time (seconds from start)
- Y-axis: Actions (list)
- Each action as horizontal bar:
  - Color by type: navigate=blue, click=cyan, wait=yellow, assert=green/red
  - Width = duration
  - Tooltip on hover: details + screenshot thumbnail
- Current action indicator: vertical line
- Zoom: scroll to zoom, drag to pan

**Live Log Panel**
- Height: 300px
- Monospace font, 13px
- Color-coded lines:
  - Info: gray
  - Success: green
  - Warning: yellow
  - Error: red
- Auto-scroll to bottom
- Search/filter input
- Export button

**Screenshots Panel**
- Grid view, 4 columns
- Thumbnail size: 160x90px
- On click: opens lightbox
- Shows: step number, timestamp, status
- Auto-refresh during execution

#### Animations
- Status bar: smooth transitions between states
- Waterfall bars: grow from left on complete
- Live log: lines fade in from bottom
- Pulse animation on "执行中" indicator

---

### 4.6 Reports Page

#### Layout Structure
- Header + Filter Bar
- Summary Cards (4 columns)
- Reports List / Trend Chart
- Screenshots Gallery

#### Sections Detail

**Filter Bar**
- Date range: Last 7 days | 30 days | Custom
- Project filter
- Status filter: All | Passed | Failed
- Search: by execution ID or script name

**Summary Cards (4 columns)**
1. **总执行次数**: Large number, trend arrow
2. **平均通过率**: Percentage with mini chart
3. **平均执行时长**: Time with comparison
4. **失败次数**: Number with failure rate

**Reports List**
- Table columns:
  - 执行ID (clickable link)
  - 脚本名称
  - 执行时间
  - 时长
  - 状态 (Pass/Fail badge)
  - 通过率 (progress bar)
  - 操作 (查看 | 下载 | 删除)
- Row click: opens report detail

**Trend Chart**
- Line chart: Pass rate over time
- Bar chart: Execution count
- Dual Y-axis
- Interactive legend
- Time range selector

**Report Detail View**
- Modal or slide-in panel (width: 80%)
- Sections:
  - Header: ID, time, duration, status
  - Summary: stats cards
  - Steps table: each action with result
  - Screenshots: gallery with step association
  - Video: playback player
  - Log: expandable full log

**Screenshots Gallery**
- Masonry grid layout
- Thumbnail with overlay on hover
- Filter: All | Failed steps only
- Click: opens lightbox with prev/next

**Video Player**
- Custom controls
- Timeline with step markers
- Play/pause, speed control (0.5x - 2x)
- Fullscreen support

#### Animations
- Cards: count up animation
- Charts: draw on scroll into view
- Gallery: masonry layout animation
- Lightbox: fade in with scale

---

### 4.7 Settings Page

#### Layout Structure
- Header
- Settings Tabs (horizontal)
  - Tab Navigation
  - Tab Content Area

#### Sections Detail

**Tab Navigation**
- Horizontal tabs, sticky
- Tabs:
  1. 通用设置 (General)
  2. 集成配置 (Integrations)
  3. 执行配置 (Execution)
  4. 通知设置 (Notifications)
  5. 用户管理 (Users) - admin only
  6. API 密钥 (API Keys)

**General Settings Tab**
- Platform name input
- Logo upload
- Default language selector
- Timezone selector
- Theme preference (Dark/Light/Auto)
- Auto-save toggle

**Integrations Tab**
- JIRA integration:
  - URL input
  - API Token input (masked)
  - Project key selector
  - Test connection button
- Git integration:
  - Repository URL
  - Branch selector
  - Webhook URL (copyable)
- Slack/Teams notification:
  - Webhook URL
  - Channel selector
  - Test button

**Execution Config Tab**
- Default browser: Chrome | Firefox | Safari | Edge
- Headless mode toggle
- Screenshot on failure toggle
- Video recording toggle
- Default viewport size
- Timeout settings:
  - Page load timeout
  - Element wait timeout
  - Script execution timeout
- Parallel execution limit

**Notifications Tab**
- Email settings:
  - SMTP configuration
  - Default recipients
- Event triggers:
  - On execution complete
  - On failure only
  - Daily summary
- Template editor (basic)

**Users Tab**
- User list table:
  - Avatar + Name
  - Email
  - Role (Admin/Member/Viewer)
  - Status
  - Last active
  - Actions
- "邀请用户" button
- Role management

**API Keys Tab**
- Keys list:
  - Name
  - Key (masked, copyable)
  - Created date
  - Last used
  - Permissions
  - Actions
- "生成新密钥" button
- Permission selector modal

**Form Styling**
- Labels: 14px, --color-text-secondary
- Inputs: height 40px, bg --color-bg-elevated
- Focus: cyan border glow
- Toggle switches: cyan when on
- Buttons: consistent with global

#### Animations
- Tab switch: content fade slide (0.2s)
- Toggle: smooth slide animation
- Save: button loading state, then success checkmark
- Test connection: spinner, then result indicator

---

## 5. Technical Requirements

### 5.1 CDN Links

```html
<!-- React 18 -->
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>

<!-- Babel for JSX -->
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

<!-- Tailwind CSS -->
<script src="https://cdn.tailwindcss.com"></script>

<!-- Lucide Icons -->
<script src="https://unpkg.com/lucide@latest"></script>

<!-- Framer Motion -->
<script src="https://unpkg.com/framer-motion@10.16.4/dist/framer-motion.js"></script>

<!-- Three.js -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>

<!-- Recharts -->
<script src="https://unpkg.com/recharts/umd/Recharts.js"></script>

<!-- Date-fns -->
<script src="https://cdn.jsdelivr.net/npm/date-fns@2.30.0/index.min.js"></script>
```

### 5.2 Tailwind Configuration

```javascript
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#0a0a0f',
        'background-secondary': '#12121a',
        'background-tertiary': '#1a1a25',
        'background-elevated': '#222230',
        accent: {
          cyan: '#00d4ff',
          purple: '#7c3aed',
          blue: '#3b82f6',
          green: '#10b981',
          yellow: '#f59e0b',
          red: '#ef4444',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.5s ease-out forwards',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'float': 'float 3s ease-in-out infinite',
        'spin-slow': 'spin 8s linear infinite',
        'border-flow': 'borderFlow 3s ease infinite',
      },
      keyframes: {
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 5px rgba(0, 212, 255, 0.5)' },
          '50%': { boxShadow: '0 0 20px rgba(0, 212, 255, 0.8)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        borderFlow: {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
      },
    },
  },
}
```

### 5.3 CSS Variables Setup

```css
:root {
  /* Colors */
  --color-bg-primary: #0a0a0f;
  --color-bg-secondary: #12121a;
  --color-bg-tertiary: #1a1a25;
  --color-bg-elevated: #222230;

  --color-accent-cyan: #00d4ff;
  --color-accent-purple: #7c3aed;
  --color-accent-blue: #3b82f6;
  --color-accent-green: #10b981;
  --color-accent-yellow: #f59e0b;
  --color-accent-red: #ef4444;

  --color-text-primary: #ffffff;
  --color-text-secondary: #a1a1aa;
  --color-text-muted: #71717a;

  /* Glassmorphism */
  --glass-bg: rgba(18, 18, 26, 0.7);
  --glass-border: rgba(255, 255, 255, 0.08);
  --glass-blur: blur(20px);

  /* Spacing */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;

  /* Radius */
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;

  /* Shadows */
  --shadow-glow-cyan: 0 0 20px rgba(0, 212, 255, 0.3);
  --shadow-glow-purple: 0 0 20px rgba(124, 58, 237, 0.3);
}
```

---

## 6. Image Requirements

### 6.1 Global Images

| Purpose | Search Keywords |
|---------|-----------------|
| Logo | "tech logo icon", "abstract geometric logo", "futuristic symbol", "neon blue gradient logo" |
| Empty States | "empty state illustration", "no data tech illustration", "dark theme empty state", "minimal tech illustration" |
| Error States | "error 404 illustration", "something went wrong tech", "dark error page", "system error graphic" |

### 6.2 Page-Specific Images

**Index Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Dashboard Hero | "dashboard tech background", "data visualization dark", "neon grid background", "futuristic dashboard ui" |
| Feature Icons | "automation icon", "testing icon", "AI icon", "script icon", "report icon" |

**US Management Page**
| Purpose | Search Keywords |
|---------|-----------------|
| AI Processing | "AI processing animation", "neural network visualization", "data processing tech", "AI analysis graphic" |
| Import Illustration | "file upload illustration", "import data tech", "document upload icon", "cloud import graphic" |

**Test Cases Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Test Case Icons | "test case icon", "quality assurance icon", "checklist tech icon", "verification icon" |
| Priority Badges | "priority badge icon", "urgent indicator", "level badge design" |

**Script Studio Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Code Editor Theme | "dark code editor", "syntax highlighting", "programming IDE dark theme" |
| Visual Blocks | "visual programming blocks", "node editor ui", "flow chart components", "drag drop interface" |

**Execution Hub Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Execution Animation | "loading animation tech", "progress indicator", "process running graphic", "execution flow animation" |
| Waterfall Chart | "waterfall chart ui", "timeline visualization", "gantt chart dark", "execution timeline" |

**Reports Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Report Graphics | "analytics dashboard", "report visualization", "data chart dark theme", "statistics graphic" |
| Screenshot Gallery | "screenshot thumbnail grid", "image gallery ui", "media gallery dark" |
| Video Player | "video player ui", "media player controls", "playback interface" |

**Settings Page**
| Purpose | Search Keywords |
|---------|-----------------|
| Integration Icons | "JIRA logo", "GitHub icon", "Slack icon", "webhook icon", "API integration" |
| Settings Graphics | "settings configuration", "system preferences", "gear icon tech" |

---

## 7. Navigation Structure

### 7.1 Sidebar Navigation

| Order | Label | Icon | Target | Badge |
|-------|-------|------|--------|-------|
| 1 | 仪表盘 | LayoutDashboard | index.html | - |
| 2 | US 需求管理 | FileText | us-management.html | New count |
| 3 | 测试用例 | CheckSquare | test-cases.html | Total count |
| 4 | 脚本工作室 | Code2 | script-studio.html | - |
| 5 | 执行中心 | PlayCircle | execution-hub.html | Running indicator |
| 6 | 报告中心 | BarChart3 | reports.html | - |
| 7 | 系统设置 | Settings | settings.html | - |

### 7.2 Sidebar Specifications

- Width: 240px (collapsible to 64px)
- Background: var(--color-bg-secondary)
- Border-right: 1px solid rgba(255,255,255,0.05)
- Logo area: height 64px, centered
- Nav items: height 44px, padding 12px 16px
- Active item: bg rgba(0,212,255,0.1), left border 3px cyan
- Hover: bg rgba(255,255,255,0.05)
- Icons: 20px, color var(--color-text-secondary)
- Labels: 14px, color var(--color-text-primary)

### 7.3 User Dropdown Menu

| Label | Icon | Action |
|-------|------|--------|
| 个人资料 | User | Navigate to profile |
| 我的设置 | Settings2 | Navigate to settings |
| 帮助中心 | HelpCircle | Open help modal |
| 退出登录 | LogOut | Logout action |

### 7.4 Breadcrumb Rules

- Format: 首页 / 当前页面
- Separator: ChevronRight icon
- Clickable except current page
- Max depth: 3 levels

---

## 8. Component Library

### 8.1 Buttons

**Primary Button**
```
Background: linear-gradient(135deg, #00d4ff, #7c3aed)
Text: white, 14px, font-medium
Padding: 10px 20px
Border-radius: 8px
Hover: brightness(1.1), shadow-glow
Active: scale(0.98)
Disabled: opacity 0.5, no gradient
```

**Secondary Button**
```
Background: transparent
Border: 1px solid rgba(255,255,255,0.2)
Text: white, 14px
Hover: bg rgba(255,255,255,0.05)
```

**Ghost Button**
```
Background: transparent
Text: var(--color-text-secondary)
Hover: text white, bg rgba(255,255,255,0.05)
```

### 8.2 Cards

**Standard Card**
```
Background: var(--glass-bg)
Border: 1px solid var(--glass-border)
Border-radius: 12px
Padding: 24px
Backdrop-filter: blur(20px)
Hover: translateY(-2px), shadow-lg
```

**Stats Card**
```
Extends Standard Card
Border-left: 3px solid accent color
Icon: 24px, accent color
Number: 32px, bold, white
Label: 14px, secondary
```

### 8.3 Badges

**Status Badge**
```
Padding: 4px 12px
Border-radius: 9999px
Font-size: 12px
Font-weight: 500
Variants:
- Success: bg-green-500/20, text-green-400
- Warning: bg-yellow-500/20, text-yellow-400
- Error: bg-red-500/20, text-red-400
- Info: bg-blue-500/20, text-blue-400
- Neutral: bg-gray-500/20, text-gray-400
```

**Priority Badge**
```
Same as Status Badge but:
- P0: red
- P1: orange
- P2: yellow
- P3: green
```

### 8.4 Inputs

**Text Input**
```
Height: 40px
Background: var(--color-bg-elevated)
Border: 1px solid rgba(255,255,255,0.1)
Border-radius: 8px
Padding: 0 12px
Font-size: 14px
Color: white
Placeholder: var(--color-text-muted)
Focus: border-cyan, shadow-glow-cyan
```

**Textarea**
```
Extends Text Input
Min-height: 100px
Padding: 12px
Resize: vertical
```

### 8.5 Modals

**Standard Modal**
```
Overlay: bg-black/60, backdrop-blur-sm
Container: max-width 500px, centered
Background: var(--color-bg-secondary)
Border: 1px solid var(--glass-border)
Border-radius: 16px
Padding: 24px
Animation: scale in 0.3s
```

### 8.6 Tables

**Data Table**
```
Width: 100%
Header: bg var(--color-bg-tertiary), text secondary
Row: border-bottom 1px solid rgba(255,255,255,0.05)
Row hover: bg rgba(255,255,255,0.02)
Cell padding: 12px 16px
Font-size: 14px
```

### 8.7 Tooltips

**Standard Tooltip**
```
Background: var(--color-bg-elevated)
Border: 1px solid var(--glass-border)
Border-radius: 6px
Padding: 8px 12px
Font-size: 12px
Color: white
Arrow: 6px
Animation: fade in 0.15s
```

---

## 9. Responsive Breakpoints

| Breakpoint | Width | Layout Changes |
|------------|-------|----------------|
| Mobile | < 640px | Single column, sidebar as drawer, stacked cards |
| Tablet | 640-1024px | 2-column grids, collapsible sidebar |
| Desktop | 1024-1440px | Full layout, 3-4 column grids |
| Large | > 1440px | Max-width container (1600px), centered |

---

## 10. Accessibility Requirements

- Minimum contrast ratio: 4.5:1 for text
- Focus indicators: visible cyan outline
- Keyboard navigation: full support
- ARIA labels: all interactive elements
- Reduced motion: respect prefers-reduced-motion
- Screen reader: semantic HTML structure

---

## 11. Performance Guidelines

- Lazy load images and heavy components
- Debounce search inputs (300ms)
- Virtualize long lists (>100 items)
- Optimize animations with will-change
- Use CSS transforms over position changes
- Minimize re-renders with React.memo

---

*Document Version: 1.0*
*Last Updated: 2024*
*Platform: AutoTest AI - 智能自动化测试平台*

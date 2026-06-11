import type { ReactElement } from 'react'

import type { ProjectCard } from '../features/types'

export type Translator = (en: string, zh: string) => string

export type UIMessage = {
  role: 'user' | 'agent'
  time: string
  name?: string
  text?: string
  html?: string
}

export const DRAFT_SETUPS = [
  {
    id: 'DR-SETUP-1',
    title: 'Payments Platform Migration',
    status: 'Awaiting Git repo binding',
    next: 'Connect checkout and payment-service repositories',
  },
  {
    id: 'DR-SETUP-2',
    title: 'Identity Recovery Upgrade',
    status: 'Waiting UX board import',
    next: 'Attach sign-in fallback flows and recovery states',
  },
]

export function formatTime(date = new Date()) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function badge(text: string, tone: 'progress' | 'active' | 'info' | 'review' | 'danger' = 'info') {
  const styleMap: Record<string, string> = {
    progress: 'background:rgba(253,214,99,0.1);color:var(--accent-amber);border:1px solid rgba(253,214,99,0.2);',
    active: 'background:rgba(129,201,149,0.1);color:var(--accent-green);border:1px solid rgba(129,201,149,0.2);',
    info: 'background:rgba(138,180,248,0.1);color:var(--accent-blue);border:1px solid rgba(138,180,248,0.2);',
    review: 'background:rgba(197,138,249,0.1);color:var(--accent-purple);border:1px solid rgba(197,138,249,0.2);',
    danger: 'background:rgba(242,139,130,0.1);color:var(--accent-red);border:1px solid rgba(242,139,130,0.2);',
  }

  return `<span class="status-badge" style="${styleMap[tone]}">${text}</span>`
}

export function miniChip(label: string, tone = 'info') {
  return `<span class="mini-chip ${tone}">${label}</span>`
}

export function statusTone(status: string) {
  const normalized = status.toLowerCase()
  if (normalized.includes('progress') || normalized.includes('execut') || normalized.includes('running') || normalized.includes('analysis')) return 'info'
  if (normalized.includes('review') || normalized.includes('pending') || normalized.includes('waiting')) return 'warn'
  if (normalized.includes('fail') || normalized.includes('block') || normalized.includes('elevated') || normalized.includes('high')) return 'bad'
  if (normalized.includes('pass') || normalized.includes('approved') || normalized.includes('ready') || normalized.includes('stable') || normalized.includes('active')) return 'good'
  return 'info'
}

export function agentIcon() {
  return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg>'
}

export function ghostButton(label: string, action: string, icon?: string, dataAttrs: Record<string, string> = {}) {
  const attrs = Object.entries(dataAttrs).map(([key, value]) => `data-${key}="${value}"`).join(' ')
  return `<button class="ghost-chip" data-action="${action}" ${attrs}>${icon ? `<i class="${icon}"></i>` : ''}${label}</button>`
}

export function surfaceRow(title: string, subtitle: string, meta: string[] = [], actionHtml = '') {
  return `
    <div class="surface-row">
      <div class="surface-row-main">
        <div class="surface-row-title">${title}</div>
        <div class="surface-row-subtitle">${subtitle}</div>
        ${meta.length ? `<div class="surface-row-meta">${meta.join('')}</div>` : ''}
      </div>
      ${actionHtml}
    </div>
  `
}

export function summaryStat(label: string, value: string, note = '') {
  return `
    <div class="surface-stat">
      <div class="surface-stat-label">${label}</div>
      <div class="surface-stat-value">${value}</div>
      ${note ? `<div class="surface-stat-note">${note}</div>` : ''}
    </div>
  `
}

export function moduleItem(text: string, badgeText = '') {
  return `
    <div class="module-item">
      <div class="module-item-name"><i class="fa-solid fa-circle-nodes" style="color:var(--text-tertiary)"></i>${text}</div>
      ${badgeText ? `<span class="risk-badge medium">${badgeText}</span>` : ''}
    </div>
  `
}

export function panelActivity(items: string[]) {
  return `
    <div class="panel-section-label">Recent Activity</div>
    ${items.map((item) => `
      <div class="module-item">
        <div class="module-item-name"><i class="fa-solid fa-clock-rotate-left" style="color:var(--text-tertiary)"></i>${item}</div>
      </div>
    `).join('')}
  `
}

export function heroCard(icon: string, title: string, copy: string, action: string, actionLabel: string) {
  return `
    <div class="hero-card" data-action="${action}">
      <div class="hero-card-icon"><i class="${icon}"></i></div>
      <div class="hero-card-title">${title}</div>
      <div class="hero-card-copy">${copy}</div>
      <div class="collection-card-footer"><span class="collection-card-subtitle">${actionLabel}</span><i class="fa-solid fa-arrow-right" style="color:var(--text-tertiary);font-size:11px;"></i></div>
    </div>
  `
}

export function projectDecoration(project: ProjectCard) {
  if (project.id === 'proj_payment') {
    return {
      subtitle: 'Checkout, refunds, and promotion orchestration',
      baseline: 'Official System Image v1.4.2',
      modules: 45,
      tests: 1204,
      docs: 18,
      overallRisk: 'Elevated',
      nextAction: 'Resolve one failed run and one pending merge',
      sources: [
        'Git · payment-system / checkout-ui',
        'US Docs · PRD bundle and acceptance notes',
        'UX Boards · checkout, refund, fallback states',
        'Historical Assets · regression and flaky failure history',
      ],
    }
  }

  return {
    subtitle: project.summary,
    baseline: project.system_image_status === 'ready' ? 'Official System Image v1.0.0' : 'System Image not initialized',
    modules: 18,
    tests: 124,
    docs: 4,
    overallRisk: project.risk === 'medium' ? 'Elevated' : project.risk === 'high' ? 'Critical' : 'Stable',
    nextAction: project.status === 'draft' ? 'Connect repositories and initialize the system image' : 'Review current blockers and open approvals',
    sources: [
      'Git · primary service repository',
      'US Docs · imported requirement bundle',
      'UX Boards · optional reference boards',
    ],
  }
}

export function projectCardMarkup(project: ProjectCard) {
  const decoration = projectDecoration(project)
  return `
    <div class="collection-card">
      <div class="collection-card-title">${project.name}</div>
      <div class="collection-card-copy">${decoration.subtitle}</div>
      <div class="collection-card-meta">
        ${miniChip(project.active_version || 'No active version', 'info')}
        ${miniChip(decoration.overallRisk, statusTone(decoration.overallRisk))}
        ${miniChip(`${project.progress}%`, 'good')}
      </div>
      <div class="collection-card-footer">
        <span class="collection-card-subtitle">${decoration.nextAction}</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap;width:100%;justify-content:flex-end;">
          <button class="pill-chip" data-action="open_version_create" data-project="${project.id}"><i class="fa-solid fa-code-branch"></i>Create Version</button>
          <button class="pill-chip primary" data-action="open_project" data-project="${project.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>
        </div>
      </div>
    </div>
  `
}

export function draftCardMarkup(draft: { title: string; status: string; next: string }) {
  return `
    <div class="collection-card">
      <div class="collection-card-title">${draft.title}</div>
      <div class="collection-card-copy">${draft.status}</div>
      <div class="collection-card-meta">
        ${miniChip('draft', 'warn')}
        ${miniChip('setup', 'info')}
      </div>
      <div class="collection-card-footer">
        <span class="collection-card-subtitle">${draft.next}</span>
        <div style="display:flex;width:100%;justify-content:flex-end;">
          <button class="pill-chip" data-action="open_project_create"><i class="fa-solid fa-arrow-right"></i>Continue</button>
        </div>
      </div>
    </div>
  `
}

export function message(role: UIMessage['role'], payload: Omit<UIMessage, 'role'>): UIMessage {
  return { role, ...payload }
}

export function renderPrototypeMessage(messageValue: UIMessage): ReactElement {
  if (messageValue.role === 'user') {
    return (
      <div className="message user message-in" key={`${messageValue.time}-${messageValue.text}`}>
        <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=28" alt="User" className="message-avatar" />
        <div className="message-body">
          <div className="message-meta"><span className="time">{messageValue.time}</span><span className="name">You</span></div>
          <div className="message-bubble">{messageValue.text}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="message agent message-in" key={`${messageValue.time}-${messageValue.name ?? 'agent'}`}>
      <div className="agent-avatar" dangerouslySetInnerHTML={{ __html: agentIcon() }} />
      <div className="message-body" style={{ flex: 1, maxWidth: '85%' }}>
        <div className="message-meta"><span className="name">{messageValue.name || 'Nasus Agent'}</span><span className="time">{messageValue.time}</span></div>
        <div className="message-bubble" dangerouslySetInnerHTML={{ __html: messageValue.html ?? '' }} />
      </div>
    </div>
  )
}

export function topLevelViewMeta(viewId: 'welcome' | 'build' | 'dashboard', tr: Translator) {
  const meta = {
    welcome: {
      title: tr('Welcome to Nasus', '欢迎来到 Nasus'),
      badge: badge(tr('Studio Home', '工作室首页'), 'info'),
      panelTitle: tr('Studio Overview', '工作室概览'),
      placeholder: tr('Ask Nasus to create a project, resume work, or explain what changed.', '让 Nasus 帮你创建项目、恢复工作，或解释最近发生了什么。'),
    },
    build: {
      title: tr('Build', '创建项目'),
      badge: badge(tr('Project Entry', '项目入口'), 'info'),
      panelTitle: tr('Build Context', '创建上下文'),
      placeholder: tr('Ask Nasus to create a project, import Git, or initialize a system image.', '让 Nasus 帮你创建项目、导入 Git，或初始化系统画像。'),
    },
    dashboard: {
      title: tr('Dashboard', '全局仪表盘'),
      badge: badge(tr('Global Health', '全局健康度'), 'active'),
      panelTitle: tr('Global Signals', '全局信号'),
      placeholder: tr('Ask for blocked releases, project risk, or current testing progress.', '查询阻塞发布、项目风险，或当前测试进度。'),
    },
  }

  return meta[viewId]
}

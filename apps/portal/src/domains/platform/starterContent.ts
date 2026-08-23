import type { DocumentationEntry } from './types/content'
import type { ProjectCard } from './types/project'

export const starterProjects: ProjectCard[] = [
  {
    id: 'local_payment',
    name: 'Payment System',
    code: 'PAY',
    summary: 'Checkout, saved cards, refunds, and release quality closure.',
    status: 'active',
    risk: 'medium',
    progress: 68,
    active_version: '2026.Q2',
    blocked_items: 2,
    pending_approvals: 1,
    system_image_status: 'ready',
    preview_only: true,
  },
  {
    id: 'local_growth',
    name: 'Growth Console',
    code: 'GRO',
    summary: 'Campaign configuration, user targeting, and approval handoff.',
    status: 'draft',
    risk: 'low',
    progress: 24,
    active_version: 'Discovery',
    blocked_items: 0,
    pending_approvals: 0,
    system_image_status: 'draft',
    preview_only: true,
  },
]

export const fallbackDocumentationEntries: DocumentationEntry[] = [
  {
    id: 'system-image',
    title: 'System Image',
    copy: 'The continuously updated project baseline built from code, US documents, and test assets.',
    category: 'Concept',
  },
  {
    id: 'agent-service',
    title: 'Agent Service',
    copy: 'The planner, memory, tool router, and swarm runtime that makes every action conversational.',
    category: 'Concept',
  },
  {
    id: 'quality-loop',
    title: 'Quality Loop',
    copy: 'The evidence-driven flow from impact analysis to release assessment and baseline write-back.',
    category: 'Guide',
  },
]

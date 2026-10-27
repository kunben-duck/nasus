import type { ProjectRouteContext } from './ProjectRouteTypes'
import type { KnowledgeCodeReference } from '../../domains/system-image/types'

export type GovernanceApprovalCardView = {
  id: string
  title: string
  summary: string
  status: string
}

export type SystemImageKnowledgeCardView = {
  id: string
  name: string
  type: string
  branch: string
  confidence: string
  relationCount: number | null
  codeReference?: KnowledgeCodeReference | null
}

export type RunCardView = {
  id: string
  title: string
  summary: string
  status: string
  channel: string
}

export function governanceSectionModel(context: ProjectRouteContext, approvalId?: string) {
  const approvals: GovernanceApprovalCardView[] = (context.workspace?.approvals ?? []).map((approval) => ({
    id: approval.id,
    title: approval.title,
    summary: approval.summary,
    status: approval.status,
  }))
  const selected = approvalId ? approvals.find((approval) => approval.id === approvalId) : approvals[0]

  return { approvals, selected }
}

export function knowledgeSectionModel(context: ProjectRouteContext, objectId?: string) {
  const limited = context.systemImage?.visibility?.mode === 'source_filtered'
  const withheld = context.systemImage?.visibility?.withheld_sections ?? []
  const objects: SystemImageKnowledgeCardView[] = (context.systemImage?.objects ?? []).map((object) => ({
    id: object.id,
    name: object.name,
    type: object.type,
    branch: object.branch,
    confidence: object.confidence,
    relationCount: limited ? null : object.relations.length,
    codeReference: object.code_reference,
  }))
  const selected = objectId ? objects.find((item) => item.id === objectId) : undefined

  return {
    objects,
    limited,
    selectedName: selected?.name ?? (limited ? 'Authorized code objects' : context.systemImage?.summary ?? 'Project context graph'),
    selectedDescription: selected
      ? `${selected.type} · ${selected.branch}`
      : limited ? 'Inspect source-pinned code objects available to you.'
        : 'Explore materialized code, US, and test context produced by the system image.',
    objectCount: objects.length,
    relationshipCount: limited ? null : context.systemImage?.relationships.length ?? 0,
    chunkCount: withheld.includes('chunks') ? null : context.systemImage?.chunks.length ?? 0,
    metricCount: limited || withheld.includes('metric_snapshots') ? null : context.systemImage?.metric_snapshots.length ?? 0,
  }
}

export function runsSectionModel(context: ProjectRouteContext, runId?: string) {
  const runs: RunCardView[] = (context.workspace?.runs ?? []).map((run) => ({
    id: run.id,
    title: run.title,
    summary: run.summary,
    status: run.status,
    channel: run.channel,
  }))
  const selected = runId ? runs.find((run) => run.id === runId) : runs[0]

  return { runs, selected }
}

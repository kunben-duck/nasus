import type { ProjectRouteContext } from './ProjectRouteTypes'

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
  relationCount: number
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
  const objects: SystemImageKnowledgeCardView[] = (context.systemImage?.objects ?? []).map((object) => ({
    id: object.id,
    name: object.name,
    type: object.type,
    branch: object.branch,
    confidence: object.confidence,
    relationCount: object.relations.length,
  }))
  const selected = objectId ? objects.find((item) => item.id === objectId) : undefined

  return {
    objects,
    selectedName: selected?.name ?? context.systemImage?.summary ?? 'Project context graph',
    selectedDescription: selected
      ? `${selected.type} · ${selected.branch}`
      : 'Explore materialized code, US, and test context produced by the system image.',
    objectCount: objects.length,
    relationshipCount: context.systemImage?.relationships.length ?? 0,
    chunkCount: context.systemImage?.chunks.length ?? 0,
    metricCount: context.systemImage?.metric_snapshots.length ?? 0,
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

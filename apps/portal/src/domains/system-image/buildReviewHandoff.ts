import type { AgentGoal, AgentStep } from '../agent/types'
import { activeGoalSteps } from '../agent/activePlanPhase'
import type { ImageRevisionSummary } from './types/imageRevision'
import type { ImageBaselineOption } from './types/baseline'

export interface BuildReviewSelection { goalId: string; invocationId: string }
export interface BuildInvestigationReport {
  revision_id: string
  revision_hash: string
  request: {
    project_id: string; goal_id: string; plan_id: string; plan_digest: string
    image_revision_id: string; image_artifact_hash: string
    parent_revision_id: string | null; parent_revision_hash: string | null
    evidence_selection: { object_id: string; evidence_id: string }[]
  }
  review: {
    image_revision_id: string; image_artifact_hash: string
    policy_version: 'nasus.image-investigation-revision.v1' | 'nasus.image-investigation-revision.v2'; publication_allowed: false
    gaps: { code: string; blocks: string; reason: string; required_action: string }[]
  }
}
export interface BuildReviewHandoff {
  selection: BuildReviewSelection
  projectId: string
  image: ImageRevisionSummary
  targetBaseline: ImageBaselineOption
  investigation: BuildInvestigationReport
  goal: AgentGoal
}

export const validReviewId = (value: unknown): value is string => typeof value === 'string'
  && value.length > 0 && value.length <= 128 && value.trim() === value
  && Array.from(value).every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
export const validReviewHash = (value: unknown): value is string => typeof value === 'string'
  && /^sha256:[a-f0-9]{64}$/.test(value)

export function completionReviewStep(goal: AgentGoal): AgentStep | undefined {
  if (goal.status !== 'paused' || goal.pause_reason !== 'build_completion_review'
      || goal.goal_template !== 'system_image_build' || !validReviewId(goal.id)
      || !validReviewId(goal.project_id)) return undefined
  try {
    const acting = activeGoalSteps(goal).filter((step) => step.phase === 'acting')
    if (!acting.length || acting.some((step) => step.status !== 'completed' || !validReviewId(step.tool_invocation_id))) return undefined
    return acting.filter((step) => step.selected_tool_id === 'system_image.build.investigate').at(-1)
  } catch { return undefined }
}

export function buildReviewHref(goal: AgentGoal) {
  const step = completionReviewStep(goal)
  if (!step?.tool_invocation_id) return undefined
  const params = new URLSearchParams({ build_review_goal: goal.id, build_review_invocation: step.tool_invocation_id })
  return `/projects/${encodeURIComponent(goal.project_id!)}/knowledge?${params}`
}

export function parseBuildReviewSelection(params: URLSearchParams): BuildReviewSelection | null {
  const goals = params.getAll('build_review_goal'), commands = params.getAll('build_review_invocation')
  if (!goals.length && !commands.length) return null
  if (goals.length !== 1 || commands.length !== 1 || !validReviewId(goals[0]) || !validReviewId(commands[0])) {
    throw new Error('Build review navigation scope is invalid')
  }
  return { goalId: goals[0], invocationId: commands[0] }
}

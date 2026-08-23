import type { QueryClient } from '@tanstack/react-query'

import { platformApi } from './api'
import { normalizeProjectName } from './build-skills'
import type { DashboardData } from './types'

type BuildMessageResponse = {
  tool_invocations?: Array<{
    tool_id?: string
    result?: {
      object_refs?: string[]
    } | null
  }>
}

export function projectIdFromBuildResponse(response: unknown): string | null {
  const payload = response as BuildMessageResponse | null
  const projectInvocation = payload?.tool_invocations?.find((invocation) => invocation.tool_id === 'project.create')
  const projectRef = projectInvocation?.result?.object_refs?.find((ref) => ref.startsWith('project:'))
  return projectRef?.split(':', 2)[1] || null
}

export async function waitForCreatedProjectFromPrompt(queryClient: QueryClient, prompt: string) {
  const requestedName = normalizeProjectName(prompt).toLowerCase()
  const deadline = Date.now() + 8000
  let latestDashboard: DashboardData | undefined
  while (Date.now() < deadline) {
    latestDashboard = await platformApi.getDashboard()
    queryClient.setQueryData(['dashboard'], latestDashboard)
    const created = latestDashboard.projects.find((project) => project.name.toLowerCase() === requestedName)
    if (created) return created
    await sleep(300)
  }
  return latestDashboard?.projects.find((project) => project.name.toLowerCase() === requestedName)
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

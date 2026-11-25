import { useQuery } from '@tanstack/react-query'
import { agentApi } from './api'

export function useBuildInbox(project: string, q: string, page: number, pageSize: number) {
  return useQuery({ queryKey: ['recent-build', project, q, page, pageSize], queryFn: ({ signal }) => {
    const params = new URLSearchParams({ offset: String(page * pageSize), limit: String(pageSize), q })
    if (project === 'unbound') params.set('unbound', 'true')
    else if (project) params.set('project_id', project)
    return agentApi.recentBuild(params, signal)
  } })
}

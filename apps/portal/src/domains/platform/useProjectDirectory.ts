import { useQuery } from '@tanstack/react-query'

import { platformApi } from './api'

export function useProjectDirectory() {
  const query = useQuery({ queryKey: ['dashboard'], queryFn: platformApi.getDashboard, retry: false })
  return {
    projects: query.isError ? [] : (query.data?.projects ?? []).filter((project) => !project.preview_only),
    loading: query.isPending,
    error: query.isError,
    reload: query.refetch,
    statusDependencies: [query],
  }
}

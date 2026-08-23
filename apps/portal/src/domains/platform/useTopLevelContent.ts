import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { platformApi } from './api'
import { fallbackDocumentationEntries, starterProjects } from './starterContent'

export function useBuildContent() {
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: platformApi.getDashboard })
  const buildQuery = useQuery({ queryKey: ['build'], queryFn: platformApi.getBuild })
  const projects = useMemo(() => {
    const remote = dashboardQuery.data?.projects ?? buildQuery.data?.drafts ?? []
    return remote.length ? remote : starterProjects
  }, [buildQuery.data?.drafts, dashboardQuery.data?.projects])

  return {
    projects,
    dashboardQuery,
    buildQuery,
    statusDependencies: [dashboardQuery, buildQuery],
  }
}

export function useDashboardContent() {
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: platformApi.getDashboard })
  const projects = useMemo(() => {
    if (dashboardQuery.data) return dashboardQuery.data.projects
    return dashboardQuery.isError ? starterProjects : []
  }, [dashboardQuery.data, dashboardQuery.isError])

  return {
    projects,
    dashboardQuery,
    statusDependencies: [dashboardQuery],
  }
}

export function useDocumentationContent() {
  const documentationQuery = useQuery({ queryKey: ['documentation'], queryFn: platformApi.getDocumentation })
  const entries = documentationQuery.data?.length ? documentationQuery.data : fallbackDocumentationEntries

  return {
    entries,
    documentationQuery,
    statusDependencies: [documentationQuery],
  }
}

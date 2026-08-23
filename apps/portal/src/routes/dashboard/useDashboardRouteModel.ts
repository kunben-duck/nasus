import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

import type { ProjectCard } from '../../domains/platform/types'
import { useDashboardContent } from '../../domains/platform/useTopLevelContent'

export function useDashboardRouteModel() {
  const navigate = useNavigate()
  const dashboardContent = useDashboardContent()

  const openProject = useCallback(
    (project: ProjectCard) => {
      if (project.preview_only) {
        navigate('/build')
        return
      }
      navigate(`/projects/${encodeURIComponent(project.id)}`)
    },
    [navigate],
  )

  return {
    projects: dashboardContent.projects,
    openProject,
    statusDependencies: dashboardContent.statusDependencies,
  }
}

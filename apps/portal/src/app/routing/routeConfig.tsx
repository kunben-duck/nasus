import { Navigate } from 'react-router-dom'
import type { RouteObject } from 'react-router-dom'

import {
  buildElement,
  dashboardElement,
  documentationElement,
  loginElement,
  projectGovernanceElement,
  projectKnowledgeElement,
  projectOverviewElement,
  projectReleaseReadinessElement,
  projectRunsElement,
  projectVersionCreateElement,
  projectVersionsElement,
  projectWorkspaceElement,
  registerElement,
  requireAuthElement,
  welcomeElement,
} from './routeElements'

export const appRoutes: RouteObject[] = [
  {
    path: '/',
    element: <Navigate to="/welcome" replace />,
  },
  {
    path: '/welcome',
    element: welcomeElement,
  },
  {
    path: '/login',
    element: loginElement,
  },
  {
    path: '/register',
    element: registerElement,
  },
  {
    element: requireAuthElement,
    children: [
      {
        path: '/build',
        element: buildElement,
      },
      {
        path: '/build/create-project',
        element: buildElement,
      },
      {
        path: '/dashboard',
        element: dashboardElement,
      },
      {
        path: '/documentation',
        element: documentationElement,
      },
      {
        path: '/projects/:projectId',
        element: projectOverviewElement,
      },
      {
        path: '/projects/:projectId/versions',
        element: projectVersionsElement,
      },
      {
        path: '/projects/:projectId/versions/create',
        element: projectVersionCreateElement,
      },
      {
        path: '/projects/:projectId/versions/new',
        element: projectVersionCreateElement,
      },
      {
        path: '/projects/:projectId/workspaces/:usId',
        element: projectWorkspaceElement,
      },
      {
        path: '/projects/:projectId/knowledge',
        element: projectKnowledgeElement,
      },
      {
        path: '/projects/:projectId/knowledge/:objectId',
        element: projectKnowledgeElement,
      },
      {
        path: '/projects/:projectId/runs',
        element: projectRunsElement,
      },
      {
        path: '/projects/:projectId/runs/:runId',
        element: projectRunsElement,
      },
      {
        path: '/projects/:projectId/governance',
        element: projectGovernanceElement,
      },
      {
        path: '/projects/:projectId/governance/:approvalId',
        element: projectGovernanceElement,
      },
      {
        path: '/projects/:projectId/approvals/:approvalId',
        element: projectGovernanceElement,
      },
      {
        path: '/projects/:projectId/release-readiness',
        element: projectReleaseReadinessElement,
      },
    ],
  },
  {
    path: '/prototype/:viewId?',
    element: <Navigate to="/build" replace />,
  },
  {
    path: '*',
    element: <Navigate to="/build" replace />,
  },
]

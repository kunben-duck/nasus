import { createBrowserRouter, Navigate } from 'react-router-dom'

import { PrototypeStudio } from './PrototypeStudio'
import { WelcomePage } from '../pages/WelcomePage'
import { BuildPage } from '../pages/BuildPage'
import { DashboardPage } from '../pages/DashboardPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/welcome" replace />,
  },
  {
    path: '/welcome',
    element: <WelcomePage />,
  },
  {
    path: '/build',
    element: <BuildPage />,
  },
  {
    path: '/build/create-project',
    element: <PrototypeStudio />,
  },
  {
    path: '/dashboard',
    element: <DashboardPage />,
  },
  {
    path: '/documentation',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/versions',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/versions/create',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/versions/new',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/workspaces/:usId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/knowledge',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/knowledge/:objectId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/runs',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/runs/:runId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/governance',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/governance/:approvalId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/approvals/:approvalId',
    element: <PrototypeStudio />,
  },
  {
    path: '/projects/:projectId/release-readiness',
    element: <PrototypeStudio />,
  },
  {
    path: '/prototype/:viewId?',
    element: <PrototypeStudio />,
  },
])

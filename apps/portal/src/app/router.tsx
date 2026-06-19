import { createBrowserRouter, Navigate } from 'react-router-dom'

import { NasusStudio } from './NasusStudio'

const studioElement = <NasusStudio />

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/build" replace />,
  },
  {
    path: '/welcome',
    element: <Navigate to="/build" replace />,
  },
  {
    path: '/build',
    element: studioElement,
  },
  {
    path: '/build/create-project',
    element: studioElement,
  },
  {
    path: '/dashboard',
    element: studioElement,
  },
  {
    path: '/documentation',
    element: studioElement,
  },
  {
    path: '/projects/:projectId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/versions',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/versions/create',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/versions/new',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/workspaces/:usId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/knowledge',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/knowledge/:objectId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/runs',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/runs/:runId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/governance',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/governance/:approvalId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/approvals/:approvalId',
    element: studioElement,
  },
  {
    path: '/projects/:projectId/release-readiness',
    element: studioElement,
  },
  {
    path: '/prototype/:viewId?',
    element: studioElement,
  },
  {
    path: '*',
    element: <Navigate to="/build" replace />,
  },
])

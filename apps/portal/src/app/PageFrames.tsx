import type { PropsWithChildren } from 'react'
import { useParams } from 'react-router-dom'

import { WorkspaceShell } from '../components/WorkspaceShell'
import type { InspectorRailConfig } from '../components/WorkspaceShell'

export function GlobalPageFrame({
  rail,
  children,
}: PropsWithChildren<{ rail: InspectorRailConfig }>) {
  return <WorkspaceShell inspector={rail} mode="global">{children}</WorkspaceShell>
}

export function ProjectPageFrame({
  rail,
  backHref,
  backLabel,
  children,
}: PropsWithChildren<{
  rail: InspectorRailConfig
  backHref?: string
  backLabel?: string
}>) {
  const { projectId = '' } = useParams()
  return (
    <WorkspaceShell
      backHref={backHref}
      backLabel={backLabel}
      inspector={rail}
      mode="project"
      projectId={projectId}
    >
      {children}
    </WorkspaceShell>
  )
}

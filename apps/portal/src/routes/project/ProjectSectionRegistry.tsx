import { GovernanceSection } from './sections/GovernanceSection'
import { KnowledgeSection } from './sections/KnowledgeSection'
import { ReleaseReadinessSection } from './sections/ReleaseReadinessSection'
import { RunsSection } from './sections/RunsSection'
import { VersionCreateSection } from './sections/version/VersionCreateSection'
import { VersionSpaceSection } from './sections/version/VersionSpaceSection'
import { WorkspaceSection } from './sections/WorkspaceSection'
import type { ProjectRouteContext } from './ProjectRouteTypes'

export type ProjectSection =
  | 'versions'
  | 'version-create'
  | 'workspace'
  | 'knowledge'
  | 'runs'
  | 'governance'
  | 'release-readiness'

export type ProjectSectionParams = {
  usId?: string
  objectId?: string
  runId?: string
  approvalId?: string
}

export function renderProjectSection(
  section: ProjectSection,
  context: ProjectRouteContext,
  params: ProjectSectionParams,
) {
  switch (section) {
    case 'versions':
      return <VersionSpaceSection context={context} />
    case 'version-create':
      return <VersionCreateSection context={context} />
    case 'workspace':
      return <WorkspaceSection context={context} usId={params.usId} />
    case 'knowledge':
      return <KnowledgeSection context={context} objectId={params.objectId} />
    case 'runs':
      return <RunsSection context={context} runId={params.runId} />
    case 'governance':
      return <GovernanceSection context={context} approvalId={params.approvalId} />
    case 'release-readiness':
      return <ReleaseReadinessSection context={context} />
  }
}

export function titleForProjectSection(section: ProjectSection) {
  switch (section) {
    case 'versions':
      return 'Version Space'
    case 'version-create':
      return 'Create Version'
    case 'workspace':
      return 'Personal Workspace'
    case 'knowledge':
      return 'System Image Knowledge'
    case 'runs':
      return 'Runs'
    case 'governance':
      return 'Governance'
    case 'release-readiness':
      return 'Release Readiness'
  }
}

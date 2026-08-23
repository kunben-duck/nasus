import { LoginRoute } from '../../routes/auth/LoginRoute'
import { PublicAuthRoute } from '../../routes/auth/PublicAuthRoute'
import { RegisterRoute } from '../../routes/auth/RegisterRoute'
import { RequireAuth } from '../../routes/auth/RequireAuth'
import { WelcomeRoute } from '../../routes/auth/WelcomeRoute'
import { BuildRoute } from '../../routes/build/BuildRoute'
import { DashboardRoute } from '../../routes/dashboard/DashboardRoute'
import { DocumentationRoute } from '../../routes/documentation/DocumentationRoute'
import { ProjectOverviewRoute } from '../../routes/project-overview/ProjectOverviewRoute'
import { ProjectSectionRoute } from '../../routes/project/ProjectSectionRoute'

export const requireAuthElement = <RequireAuth />
export const welcomeElement = <PublicAuthRoute><WelcomeRoute /></PublicAuthRoute>
export const loginElement = <PublicAuthRoute><LoginRoute /></PublicAuthRoute>
export const registerElement = <PublicAuthRoute><RegisterRoute /></PublicAuthRoute>
export const buildElement = <BuildRoute />
export const dashboardElement = <DashboardRoute />
export const documentationElement = <DocumentationRoute />
export const projectOverviewElement = <ProjectOverviewRoute />
export const projectVersionsElement = <ProjectSectionRoute section="versions" />
export const projectVersionCreateElement = <ProjectSectionRoute section="version-create" />
export const projectWorkspaceElement = <ProjectSectionRoute section="workspace" />
export const projectKnowledgeElement = <ProjectSectionRoute section="knowledge" />
export const projectRunsElement = <ProjectSectionRoute section="runs" />
export const projectGovernanceElement = <ProjectSectionRoute section="governance" />
export const projectReleaseReadinessElement = <ProjectSectionRoute section="release-readiness" />

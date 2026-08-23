import { ProjectRouteFrame } from './ProjectRouteFrame'
import type { ProjectSection } from './ProjectSectionRegistry'
import { ProjectSectionView } from './ProjectSectionView'
import { useProjectSectionParams } from './useProjectSectionParams'

export type { ProjectSection } from './ProjectSectionRegistry'

export function ProjectSectionRoute({ section }: { section: ProjectSection }) {
  const params = useProjectSectionParams()

  return (
    <ProjectRouteFrame>
      {(context, shellState) => (
        <ProjectSectionView section={section} context={context} shellState={shellState} params={params} />
      )}
    </ProjectRouteFrame>
  )
}

import type { ProjectCard } from '../../../domains/platform/types'
import { ProjectGallery } from '../../../shared/ui/ProjectGallery'

export function BuildGalleryPanel({
  projects,
  openProject,
}: {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
}) {
  return (
    <div className="gallery-panel">
      <div className="gallery-header">
        <h2>Discover project starting points</h2>
        <button>Browse templates →</button>
      </div>
      <ProjectGallery projects={projects} openProject={openProject} />
    </div>
  )
}

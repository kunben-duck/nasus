import { BuildComposer } from '../../shared/ui/BuildComposer'
import { BuildGalleryPanel } from './components/BuildGalleryPanel'
import { BuildSidebarToggle } from './components/BuildSidebarToggle'
import { BuildSkillStrip } from './components/BuildSkillStrip'
import type { BuildHeroProps } from './BuildHeroTypes'

export function BuildHero({
  projects,
  openProject,
  prompt,
  setPrompt,
  runPrompt,
  loading,
  selectedSkillIds,
  selectedSkills,
  onToggleSkill,
  onGuessYou,
  sidebarCollapsed,
  toggleSidebar,
}: BuildHeroProps) {
  return (
    <section className="build-hero">
      <BuildSidebarToggle sidebarCollapsed={sidebarCollapsed} toggleSidebar={toggleSidebar} />
      <div className="hero-title">
        <h1>Build quality projects with Nasus</h1>
      </div>
      <BuildComposer
        prompt={prompt}
        setPrompt={setPrompt}
        runPrompt={runPrompt}
        loading={loading}
        selectedSkills={selectedSkills}
        onToggleSkill={onToggleSkill}
        onGuessYou={onGuessYou}
      />
      <BuildSkillStrip selectedSkillIds={selectedSkillIds} onToggleSkill={onToggleSkill} />
      <BuildGalleryPanel projects={projects} openProject={openProject} />
    </section>
  )
}

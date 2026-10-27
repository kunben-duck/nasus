import { BuildComposer } from '../../shared/ui/BuildComposer'
import { BuildGalleryPanel } from './components/BuildGalleryPanel'
import { BuildAgentFeedback } from './components/BuildAgentFeedback'
import { BuildSidebarToggle } from './components/BuildSidebarToggle'
import { BuildSkillStrip } from './components/BuildSkillStrip'
import type { BuildHeroProps } from './BuildHeroTypes'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function BuildHero({
  projects,
  openProject,
  prompt,
  setPrompt,
  runPrompt,
  stopPrompt,
  loading,
  streaming,
  selectedSkillIds,
  selectedSkills,
  onToggleSkill,
  onGuessYou,
  feedback,
  sidebarCollapsed,
  toggleSidebar,
}: BuildHeroProps) {
  const { t } = useI18n()
  return (
    <section className="build-hero">
      <BuildSidebarToggle sidebarCollapsed={sidebarCollapsed} toggleSidebar={toggleSidebar} />
      <div className="hero-title">
        <h1>{t('Build quality projects with Nasus')}</h1>
      </div>
      <BuildComposer
        prompt={prompt}
        setPrompt={setPrompt}
        runPrompt={runPrompt}
        stopPrompt={stopPrompt}
        loading={loading}
        streaming={streaming}
        selectedSkills={selectedSkills}
        onToggleSkill={onToggleSkill}
        onGuessYou={onGuessYou}
      />
      <BuildAgentFeedback feedback={feedback} streaming={streaming} />
      <BuildSkillStrip selectedSkillIds={selectedSkillIds} onToggleSkill={onToggleSkill} />
      <BuildGalleryPanel projects={projects} openProject={openProject} />
    </section>
  )
}

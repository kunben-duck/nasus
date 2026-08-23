import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { BuildHero } from './BuildHero'
import { useBuildRouteModel } from './useBuildRouteModel'

export function BuildRoute() {
  const model = useBuildRouteModel()

  return (
    <TopLevelStudioShell active="build" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <BuildHero
          projects={model.projects}
          openProject={model.openProject}
          prompt={model.prompt}
          setPrompt={model.setPrompt}
          runPrompt={model.runPrompt}
          loading={model.loading}
          selectedSkillIds={model.selectedSkillIds}
          selectedSkills={model.selectedSkills}
          onToggleSkill={model.toggleBuildSkill}
          onGuessYou={model.guessBuildPrompt}
          sidebarCollapsed={sidebarCollapsed}
          toggleSidebar={toggleSidebar}
        />
      )}
    </TopLevelStudioShell>
  )
}

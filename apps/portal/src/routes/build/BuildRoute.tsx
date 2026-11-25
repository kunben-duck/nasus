import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { BuildHero } from './BuildHero'
import { useBuildRouteModel } from './useBuildRouteModel'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { BuildInbox } from './BuildInbox'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function BuildRoute() {
  const [search] = useSearchParams()
  const { pathname } = useLocation()
  if (!search.has('conversation') && !search.has('session') && /^\/build\/?$/.test(pathname)) return <BuildInbox />
  const invalid = (search.has('conversation') && !/^conv_[a-zA-Z0-9_-]+$/.test(search.get('conversation')!))
    || (search.has('session') && !/^[a-zA-Z0-9-]{1,64}$/.test(search.get('session')!))
  if (invalid) return <Unavailable />
  return <BuildDetail key={search.toString()} />
}

function Unavailable() {
  const { t } = useI18n()
  return <p role="alert">{t('This conversation is unavailable.')} <Link to="/build">{t('My conversations')}</Link></p>
}

function BuildDetail() {
  const model = useBuildRouteModel()
  const { t } = useI18n()

  return (
    <TopLevelStudioShell active="build" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => model.unavailable ? <Unavailable /> : <>
        <Link className="tool-chip" to="/build">{t('My conversations')}</Link>
        <BuildHero
          conversation={model.conversation}
          sendPrompt={model.sendPrompt}
          newBuild={model.newBuild}
          prompt={model.prompt}
          setPrompt={model.setPrompt}
          runPrompt={model.runPrompt}
          stopPrompt={model.stopPrompt}
          loading={model.loading}
          streaming={model.streaming}
          selectedSkills={model.selectedSkills}
          onToggleSkill={model.toggleBuildSkill}
          onGuessYou={model.guessBuildPrompt}
          feedback={model.feedback}
          sidebarCollapsed={sidebarCollapsed}
          toggleSidebar={toggleSidebar}
        /></>}
    </TopLevelStudioShell>
  )
}

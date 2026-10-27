import type { AgentMode } from '../ProjectWorkspaceTypes'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function AgentModeTabs({
  mode,
  setMode,
}: {
  mode: AgentMode
  setMode: (mode: AgentMode) => void
}) {
  const { t } = useI18n()
  return (
    <div className="agent-heading">
      <h1>{t('Build with Agents')}</h1>
      <div className="segmented">
        <button className={mode === 'planning' ? 'active' : ''} onClick={() => setMode('planning')}>{t('Agents')}</button>
        <button className={mode === 'sources' ? 'active' : ''} onClick={() => setMode('sources')}>{t('Sources')}</button>
        <button className={mode === 'quality' ? 'active' : ''} onClick={() => setMode('quality')}>{t('Quality')}</button>
      </div>
    </div>
  )
}

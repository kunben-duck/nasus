import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function VersionCreateSection({ context }: { context: ProjectRouteContext }) {
  const { t } = useI18n()
  return (
    <>
      <div className="agent-heading">
        <h1>{t('Create Version Branch')}</h1>
        <div className="segmented">
          <button className="active">{t('Summary')}</button>
          <button>{t('Owners')}</button>
          <button>{t('Fork')}</button>
        </div>
      </div>
      <div className="source-binding-panel">
        <div className="source-binding-header">
          <div>
            <span className="eyebrow">{t('Version tool')}</span>
            <strong>{t('Use the agent to create a governed version branch')}</strong>
            <p>{t('Version creation remains a tool-backed write action. The first formal implementation should invoke version tools through ToolInvocationRuntime rather than mutating project state in the page.')}</p>
          </div>
          <span className="source-status-pill pending">{t('tool-first')}</span>
        </div>
        <div className="task-composer">
          <textarea
            data-testid="version-create-agent-input"
            value={context.prompt}
            onChange={(event) => context.setPrompt(event.target.value)}
            placeholder={t('Create a new version branch for {name}', { name: context.project.name })}
            disabled={context.loading}
          />
          <div className="task-chip-row">
            <button className="tool-chip active" disabled={context.loading}>
              {t('Version branch')} ×
            </button>
            <button className="round-icon" onClick={context.runPrompt} disabled={context.loading}>
              ↵
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

import type { StudioActionId } from '../../../domains/platform/tool-actions'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ProjectTaskComposer({
  prompt,
  setPrompt,
  runPrompt,
  stopPrompt,
  streaming,
  initializeSystemImage,
  invokeProjectAction,
  disabled,
  actionControlsDisabled,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  stopPrompt: () => void
  streaming: boolean
  initializeSystemImage: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
  disabled: boolean
  actionControlsDisabled: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="task-composer">
      <textarea
        data-testid="project-agent-input"
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder={t('Start typing a prompt to see what our agents can do')}
        disabled={disabled}
      />
      <div className="task-chip-row">
        <button className="tool-chip" disabled={actionControlsDisabled}>{t('Tools')}</button>
        <button className="tool-chip active" data-testid="tool-system-image" onClick={initializeSystemImage} disabled={actionControlsDisabled}>{t('System image')} ×</button>
        <button className="tool-chip active" onClick={() => invokeProjectAction('quality-loop.continue-goal')} disabled={actionControlsDisabled}>{t('Quality loop')} ×</button>
        <button className="tool-chip" data-testid="tool-release-gate" onClick={() => invokeProjectAction('release.assess')} disabled={actionControlsDisabled}>{t('Release gate')}</button>
        {streaming ? (
          <button className="round-icon" data-testid="project-agent-stop" onClick={stopPrompt} aria-label={t('Stop')}>■</button>
        ) : (
          <button className="round-icon" data-testid="project-agent-submit" onClick={runPrompt} disabled={disabled}>↵</button>
        )}
      </div>
    </div>
  )
}

import type { StudioActionId } from '../../../domains/platform/tool-actions'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { AgentComposer } from '../../../shared/ui/chat-composer/AgentComposer'

export function ProjectTaskComposer({
  prompt,
  promptHistory,
  setPrompt,
  runPrompt,
  stopPrompt,
  streaming,
  initializeSystemImage,
  invokeProjectAction,
  disabled,
}: {
  prompt: string
  promptHistory: readonly string[]
  setPrompt: (value: string) => void
  runPrompt: () => void
  stopPrompt: () => void
  streaming: boolean
  initializeSystemImage: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
  disabled: boolean
}) {
  const { t } = useI18n()
  return (
    <AgentComposer prompt={prompt} promptHistory={promptHistory} setPrompt={setPrompt} runPrompt={runPrompt}
      stopPrompt={stopPrompt} disabled={disabled} streaming={streaming}
      placeholder={t('Start typing a prompt to see what our agents can do')}>
      <button className="tool-chip" disabled={disabled}>{t('Tools')}</button>
      <button className="tool-chip active" data-testid="tool-system-image" onClick={initializeSystemImage} disabled={disabled}>{t('System image')} ×</button>
      <button className="tool-chip active" onClick={() => invokeProjectAction('quality-loop.continue-goal')} disabled={disabled}>{t('Quality loop')} ×</button>
      <button className="tool-chip" data-testid="tool-release-gate" onClick={() => invokeProjectAction('release.assess')} disabled={disabled}>{t('Release gate')}</button>
    </AgentComposer>
  )
}

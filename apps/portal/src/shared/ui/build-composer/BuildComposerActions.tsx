import { useI18n } from '../../i18n/I18nProvider'

export function BuildComposerActions({
  hasPrompt,
  loading,
  streaming,
  onGuessYou,
  runPrompt,
  stopPrompt,
}: {
  hasPrompt: boolean
  loading: boolean
  streaming: boolean
  onGuessYou: () => void
  runPrompt: () => void
  stopPrompt: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="composer-actions">
      <div className="composer-right">
        {!hasPrompt && !streaming ? <button className="composer-action-button guess-button" data-testid="build-agent-guess" onClick={onGuessYou} type="button">
          <span className="material-symbols-outlined action-spark" aria-hidden="true">
            auto_awesome
          </span>
          <span>{t('I guess you')}</span>
        </button> : null}
        {streaming ? (
          <button className="composer-action-button build-submit-button" data-testid="build-agent-stop" onClick={stopPrompt} type="button">
            <span className="material-symbols-outlined" aria-hidden="true">stop_circle</span>
            <span>{t('Stop')}</span>
          </button>
        ) : hasPrompt ? (
          <button className="composer-action-button build-submit-button" data-testid="build-agent-submit" onClick={runPrompt} disabled={loading}>
            <span>{loading ? t('Building...') : t('Build')}</span>
            {!loading ? <span className="action-shortcut" aria-hidden="true">Enter</span> : null}
          </button>
        ) : null}
      </div>
    </div>
  )
}

export function BuildComposerActions({
  hasPrompt,
  loading,
  onGuessYou,
  runPrompt,
}: {
  hasPrompt: boolean
  loading: boolean
  onGuessYou: () => void
  runPrompt: () => void
}) {
  return (
    <div className="composer-actions">
      <div className="composer-left">
        <button className="round-icon" aria-label="Speech to text" type="button">
          <span className="material-symbols-outlined composer-symbol" aria-hidden="true">
            mic
          </span>
        </button>
        <button className="round-icon" aria-label="Insert files" type="button">
          <span className="material-symbols-outlined composer-symbol" aria-hidden="true">
            add_circle
          </span>
        </button>
      </div>
      <div className="composer-right">
        <button className="composer-action-button guess-button" data-testid="build-agent-guess" onClick={onGuessYou} type="button">
          <span className="material-symbols-outlined action-spark" aria-hidden="true">
            auto_awesome
          </span>
          <span>I guess you</span>
        </button>
        {hasPrompt ? (
          <button className="composer-action-button build-submit-button" data-testid="build-agent-submit" onClick={runPrompt} disabled={loading}>
            <span>{loading ? 'Building...' : 'Build'}</span>
            {!loading ? <span className="action-shortcut">⌘↵</span> : null}
          </button>
        ) : null}
      </div>
    </div>
  )
}

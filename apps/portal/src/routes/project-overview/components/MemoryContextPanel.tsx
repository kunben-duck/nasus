import type { AgentMemoryContextView } from '../../../domains/agent/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function MemoryContextPanel({ context }: { context?: AgentMemoryContextView }) {
  const { t, tx } = useI18n()
  if (!context) return null

  const scopes = [
    ['Working', context.working_memory],
    ['Conversation', context.conversation_memory],
    ['Project', context.project_long_term_memory],
    ['Candidate', context.candidate_memory],
  ] as const

  return (
    <article className="agent-runtime-card memory-context-panel" data-testid="agent-memory-context-panel">
      <header>
        <span className="agent-runtime-icon memory" aria-hidden="true">◎</span>
        <div>
          <span className="eyebrow">{t('Memory context')}</span>
          <strong>{t('Evidence used by this goal')}</strong>
        </div>
        <span className="memory-context-hash" title={context.context_hash}>{shortHash(context.context_hash)}</span>
      </header>
      <p>{tx(context.context_summary)}</p>
      <div className="memory-scope-grid">
        {scopes.map(([label, value]) => (
          <div key={label}>
            <span>{tx(label)}</span>
            <strong>{Object.keys(value ?? {}).length}</strong>
          </div>
        ))}
      </div>
      <div className="agent-runtime-meta">
        <span>{t('{count} recent turns', { count: context.recent_turn_count })}</span>
        <span>{t('{count} checkpoints', { count: context.checkpoint_count })}</span>
        <span>{t('{count} retrieved refs', { count: context.retrieved_context.refs.length })}</span>
        <span>{t('{count} tools', { count: context.tool_catalog.tool_count })}</span>
      </div>
      {context.retrieved_context.summary ? (
        <div className="agent-runtime-evidence">
          <span>{t('Long-term retrieval')}</span>
          <p>{tx(context.retrieved_context.summary)}</p>
        </div>
      ) : null}
    </article>
  )
}

function shortHash(value: string) {
  const compact = value.replace('sha256:', '')
  return compact.length > 12 ? `${compact.slice(0, 12)}…` : compact
}

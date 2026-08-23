import type { AgentMemoryContextView } from '../../../domains/agent/types'

export function MemoryContextPanel({ context }: { context?: AgentMemoryContextView }) {
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
          <span className="eyebrow">Memory context</span>
          <strong>Evidence used by this goal</strong>
        </div>
        <span className="memory-context-hash" title={context.context_hash}>{shortHash(context.context_hash)}</span>
      </header>
      <p>{context.context_summary}</p>
      <div className="memory-scope-grid">
        {scopes.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{Object.keys(value ?? {}).length}</strong>
          </div>
        ))}
      </div>
      <div className="agent-runtime-meta">
        <span>{context.recent_turn_count} recent turns</span>
        <span>{context.checkpoint_count} checkpoints</span>
        <span>{context.retrieved_context.refs.length} retrieved refs</span>
        <span>{context.tool_catalog.tool_count} tools</span>
      </div>
      {context.retrieved_context.summary ? (
        <div className="agent-runtime-evidence">
          <span>Long-term retrieval</span>
          <p>{context.retrieved_context.summary}</p>
        </div>
      ) : null}
    </article>
  )
}

function shortHash(value: string) {
  const compact = value.replace('sha256:', '')
  return compact.length > 12 ? `${compact.slice(0, 12)}…` : compact
}

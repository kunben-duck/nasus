import type { ToolInvocation } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ToolInvocationRail({ invocations }: { invocations: ToolInvocation[] }) {
  const { t, tx } = useI18n()
  const visibleInvocations = invocations
    .filter((invocation) => ['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed'].includes(invocation.status))
    .slice(-4)

  if (!visibleInvocations.length) return null

  return (
    <div className="tool-invocation-rail" data-testid="tool-invocation-rail">
      <div className="tool-invocation-heading">
        <span className="eyebrow">{t('Tool runtime')}</span>
        <strong>{t('Agent actions')}</strong>
      </div>
      <div className="tool-invocation-list">
        {visibleInvocations.map((invocation) => (
          <div className={`tool-invocation-pill ${invocation.status}`} key={invocation.id}>
            <span className="tool-invocation-dot" aria-hidden="true" />
            <span className="tool-invocation-name">{invocation.tool_id}</span>
            <span className="tool-invocation-status">{tx(invocation.status.replaceAll('_', ' '))}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

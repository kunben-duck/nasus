import type { ModelRoute, SettingsConnectionResult } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ModelConnectionResult({
  activeRoute,
  testResult,
}: {
  activeRoute: ModelRoute
  testResult?: SettingsConnectionResult
}) {
  const { tx } = useI18n()
  if (!testResult) return null

  return (
    <div className={`settings-test-result ${testResult.ok ? 'success' : 'warning'}`}>
      <strong>{tx(testResult.model_route ?? activeRoute)} · {tx(testResult.runtime_mode)}</strong>
      <span>{tx(testResult.message)}</span>
    </div>
  )
}

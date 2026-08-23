import type { ModelRoute, SettingsConnectionResult } from '../../../domains/platform/types'

export function ModelConnectionResult({
  activeRoute,
  testResult,
}: {
  activeRoute: ModelRoute
  testResult?: SettingsConnectionResult
}) {
  if (!testResult) return null

  return (
    <div className={`settings-test-result ${testResult.ok ? 'success' : 'warning'}`}>
      <strong>{testResult.model_route ?? activeRoute} · {testResult.runtime_mode}</strong>
      <span>{testResult.message}</span>
    </div>
  )
}

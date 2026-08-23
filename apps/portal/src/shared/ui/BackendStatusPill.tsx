import type { BackendStatus } from '../status/backendStatus'

export type { BackendStatus } from '../status/backendStatus'

export function BackendStatusPill({ status }: { status: BackendStatus }) {
  const label = status === 'live' ? 'Live' : status === 'loading' ? 'Connecting' : 'Offline preview'
  const copy = status === 'live'
    ? 'Backend connected'
    : status === 'loading'
      ? 'Checking backend'
      : 'Using local preview data'

  return (
    <span className={`backend-status-pill ${status}`} title={copy} data-testid="backend-status-pill">
      <span className="backend-status-dot" />
      <span>{label}</span>
    </span>
  )
}

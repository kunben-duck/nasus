import type { BackendStatus } from '../../shared/status/backendStatus'
import { BackendStatusPill } from '../../shared/ui/BackendStatusPill'

export function StudioTermsBar({ backendStatus }: { backendStatus: BackendStatus }) {
  return (
    <div className="terms-bar">
      <span>Nasus first production baseline · system image + agent + quality loop</span>
      <BackendStatusPill status={backendStatus} />
      <button>Learn more</button>
      <button>Dismiss</button>
    </div>
  )
}

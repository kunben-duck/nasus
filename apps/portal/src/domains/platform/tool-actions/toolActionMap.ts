import type { StudioActionId } from './types'

export function toolIdForAction(actionId: StudioActionId): string {
  switch (actionId) {
    case 'system-image.register-sources':
      return 'system_image.sources.register'
    case 'system-image.ingest-sources':
      return 'system_image.sources.ingest'
    case 'system-image.materialize-context':
      return 'system_image.context.materialize'
    case 'system-image.initialize-baseline':
      return 'system_image.baseline.initialize'
    case 'system-image.status':
      return 'query.system_image.status'
    case 'release.assess':
      return 'release.assess'
    default:
      throw new Error(`Action ${actionId} does not map to a direct tool invocation.`)
  }
}

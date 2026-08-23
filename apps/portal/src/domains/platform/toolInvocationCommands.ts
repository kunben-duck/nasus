import { platformApi } from './api'

export function confirmToolInvocation(invocationId: string) {
  return platformApi.confirmToolInvocation(invocationId)
}

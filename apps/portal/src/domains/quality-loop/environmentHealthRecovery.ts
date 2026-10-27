import { createEnvironmentRecovery } from './environmentRecordRecovery'

export const createHealthRecovery = (storage: Parameters<typeof createEnvironmentRecovery>[0]) =>
  createEnvironmentRecovery(storage, 'nasus.health-record.v1:')
export const healthRecovery = createHealthRecovery(() => window.sessionStorage)

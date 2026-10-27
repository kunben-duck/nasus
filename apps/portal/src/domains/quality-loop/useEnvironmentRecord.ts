import { environmentRecordApi } from './environmentRecordApi'
import { environmentRecovery } from './environmentRecordRecovery'
import { useOriginalObservation } from './useOriginalObservation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'

const definition = { key: 'environment-record', api: environmentRecordApi, storage: environmentRecovery }
export function useEnvironmentRecord(plan: RunPlanArchive, binding: RunPlanBuildArchive, actorId: string, current: boolean, onFailure: () => void) {
  return useOriginalObservation(plan, binding, actorId, current, onFailure, definition)
}

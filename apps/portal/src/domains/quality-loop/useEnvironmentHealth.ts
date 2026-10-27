import { environmentHealthApi } from './environmentHealthApi'
import { healthRecovery } from './environmentHealthRecovery'
import { useOriginalObservation } from './useOriginalObservation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'

const definition = { key: 'health-record', api: environmentHealthApi, storage: healthRecovery }
export function useEnvironmentHealth(plan: RunPlanArchive, binding: RunPlanBuildArchive, actorId: string, current: boolean, onFailure: () => void) {
  return useOriginalObservation(plan, binding, actorId, current, onFailure, definition)
}

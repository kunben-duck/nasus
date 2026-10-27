import { createOriginalObservationApi } from './originalObservationApi'
import { environmentRecordIdentity, verifyEnvironmentRecord } from './environmentRecordValidation'

export const environmentRecordTool = 'quality.run_plan.record_environment'
export const environmentRecordApi = createOriginalObservationApi({ tool: environmentRecordTool,
  objectPrefix: 'run_plan_environment:', receipt: 'run_plan_environment_record', path: 'run-plan-environments',
  identity: environmentRecordIdentity, verify: verifyEnvironmentRecord })
export const requireEnvironmentCommand = environmentRecordApi.requireCommand

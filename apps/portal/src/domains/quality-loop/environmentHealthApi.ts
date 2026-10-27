import { createOriginalObservationApi } from './originalObservationApi'
import { healthRecordIdentity, verifyHealthRecord } from './environmentHealthValidation'

export const healthRecordTool = 'quality.run_plan.record_health'
export const environmentHealthApi = createOriginalObservationApi({ tool: healthRecordTool,
  objectPrefix: 'run_plan_health:', receipt: 'run_plan_health_record', path: 'run-plan-health',
  identity: healthRecordIdentity, verify: verifyHealthRecord })
export const requireHealthCommand = environmentHealthApi.requireCommand

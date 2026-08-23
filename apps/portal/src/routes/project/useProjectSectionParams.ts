import { useParams } from 'react-router-dom'

import type { ProjectSectionParams } from './ProjectSectionRegistry'

function decodeOptionalRouteParam(value?: string) {
  return value ? decodeURIComponent(value) : undefined
}

export function useProjectSectionParams(): ProjectSectionParams {
  const params = useParams()

  return {
    usId: decodeOptionalRouteParam(params.usId),
    objectId: decodeOptionalRouteParam(params.objectId),
    runId: decodeOptionalRouteParam(params.runId),
    approvalId: decodeOptionalRouteParam(params.approvalId),
  }
}

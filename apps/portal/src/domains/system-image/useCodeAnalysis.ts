import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { codeAnalysisApi } from './codeAnalysisApi'
import type { AnalysisPageSelection } from './types/codeAnalysis'

const sensitiveRead = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export interface AnalysisReadScope { projectId: string; sessionId: string; onFailure: (failed: boolean) => void }

function useFailure(isError: boolean, onFailure: AnalysisReadScope['onFailure']) {
  useEffect(() => { if (isError) onFailure(true) }, [isError, onFailure])
}

export function useCodeSourceRevisions(scope: AnalysisReadScope, cursor: string) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'analysis-revisions', scope.sessionId, cursor],
    queryFn: ({ signal }) => codeAnalysisApi.revisions(scope.projectId, cursor, signal),
  })
  useFailure(query.isError, scope.onFailure)
  return query
}

export function useCodeAnalysisList(scope: AnalysisReadScope, revisionId: string, cursor: string) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'analysis-list', scope.sessionId, revisionId, cursor],
    queryFn: ({ signal }) => codeAnalysisApi.list(scope.projectId, revisionId, cursor, signal),
  })
  useFailure(query.isError, scope.onFailure)
  return query
}

export function useCodeAnalysisPage(scope: AnalysisReadScope, revisionId: string, analysisId: string, selection: AnalysisPageSelection) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'analysis-page', scope.sessionId, revisionId, analysisId, selection],
    queryFn: ({ signal }) => codeAnalysisApi.page(scope.projectId, revisionId, analysisId, selection, signal),
  })
  useFailure(query.isError, scope.onFailure)
  return query
}

import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { readCodeMemberDelta } from './codeMemberDeltaApi'
import type { ImageReadScope } from './useImageRevisions'
import type { CodeMemberDeltaPair, CodeMemberDeltaSelection } from './types/codeMemberDelta'

export function useCodeMemberDelta(scope: ImageReadScope, pair: CodeMemberDeltaPair, selection: CodeMemberDeltaSelection) {
  const verifiedHash = useRef<string | undefined>(undefined)
  const query = useQuery({
    queryKey: ['system-image', scope.projectId, scope.sessionId, 'code-member-delta', pair, selection],
    staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: async ({ signal }) => {
      const page = await readCodeMemberDelta(scope.projectId, pair, selection, signal, verifiedHash.current)
      signal.throwIfAborted()
      verifiedHash.current = page.content_hash
      return page
    },
  })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  return query
}

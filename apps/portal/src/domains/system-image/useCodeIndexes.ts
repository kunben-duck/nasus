import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { codeIndexApi } from './codeIndexApi'
import type { CodeIndexPin, CodeIndexStatusView } from './types/codeIndex'
import type { AnalysisReadScope } from './useCodeAnalysis'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }

export function useCodeIndexList(scope: AnalysisReadScope, binding: string, cursor: string, open: boolean) {
  const query = useQuery({ ...sensitive, enabled: open,
    queryKey: ['code-index-list', scope.projectId, binding, scope.sessionId, cursor],
    queryFn: ({ signal }) => codeIndexApi.list(scope.projectId, binding, cursor, signal) })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  return query
}

export function useCodeIndexStatus(scope: AnalysisReadScope, pin: CodeIndexPin) {
  const [consent, setConsent] = useState(''), submitted = useRef(false)
  const { onFailure } = scope
  const query = useQuery({ ...sensitive,
    queryKey: ['code-index-status', scope.projectId, pin.binding_id, scope.sessionId, pin],
    queryFn: ({ signal }) => codeIndexApi.status(pin, signal),
    refetchInterval: (state) => state.state.data?.status.state === 'cancel_requested' ? 1000 : false })
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const scopeKey = JSON.stringify([pin, view?.status.epoch, query.dataUpdatedAt])
  const write = useMutation({ retry: false,
    mutationFn: ({ prepared, attempt }: { prepared: CodeIndexStatusView; attempt: string }) => codeIndexApi.cancel(prepared, attempt),
    onSuccess: async () => { await query.refetch() },
    onError: () => onFailure(true),
    onSettled: () => { submitted.current = false; setConsent('') } })
  const confirmed = !!view?.can_cancel && consent === scopeKey
  const canCancel = confirmed && !write.isPending && !write.isError
  return { query, view, write, confirmed, canCancel,
    confirm: (checked: boolean) => setConsent(checked && view?.can_cancel ? scopeKey : ''),
    reload: () => { if (!write.isPending) { setConsent(''); write.reset(); void query.refetch() } },
    cancel: () => {
      if (!view || !canCancel || submitted.current) return
      submitted.current = true; setConsent(''); write.mutate({ prepared: view, attempt: crypto.randomUUID() })
    } }
}

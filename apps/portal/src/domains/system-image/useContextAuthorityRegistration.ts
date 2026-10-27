import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { contextAuthorityRegistrationApi } from './contextAuthorityRegistrationApi'

export function useContextAuthorityRegistration(projectId: string, sessionId: string) {
  const client = useQueryClient(), submitted = useRef(false), [open, setOpen] = useState(false), [cursors, setCursors] = useState([''])
  const [selected, setSelected] = useState(''), [consent, setConsent] = useState('')
  const afterId = cursors.at(-1)!
  const list = useQuery({ queryKey: ['context-authority-backfill', projectId, sessionId, afterId],
    queryFn: ({ signal }) => contextAuthorityRegistrationApi.page(projectId, afterId, signal),
    enabled: open && !!sessionId, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' })
  const write = useMutation({ retry: false,
    mutationFn: ({ item, cursor, attempt }: { item: NonNullable<typeof list.data>['items'][number]; cursor: string; attempt: string }) =>
      contextAuthorityRegistrationApi.register(item, cursor, attempt),
    onSuccess: () => {
      setSelected(''); setConsent('')
      void list.refetch()
      void client.invalidateQueries({ queryKey: ['context-packs', projectId, sessionId] })
      void client.invalidateQueries({ queryKey: ['test-design-review-drafts', projectId, sessionId] })
    },
    onSettled: () => setConsent(''),
  })
  const failed = list.isError || write.isError
  const rows = open && !failed && !list.isFetching && !write.isPending ? list.data?.items : undefined
  const item = rows?.find((value) => value.registration_request.context_id === selected)
  const consentKey = JSON.stringify([sessionId, afterId, item, list.dataUpdatedAt])
  const confirmed = !!item && consent === consentKey
  return { open, list, write, rows, item, failed, confirmed, page: cursors.length,
    toggle: () => { if (write.isPending) return; setOpen(!open); setSelected(''); setConsent('') },
    choose: (contextId: string) => { setSelected(contextId); setConsent(''); submitted.current = false; write.reset() },
    confirm: (checked: boolean) => setConsent(checked && item ? consentKey : ''),
    save: () => { if (item && confirmed && !write.isPending && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ item, cursor: afterId, attempt: crypto.randomUUID() }) } },
    reload: () => { if (write.isPending) return; setSelected(''); setConsent(''); submitted.current = false; write.reset(); void list.refetch() },
    previous: cursors.length > 1 ? () => { setSelected(''); setConsent(''); setCursors(cursors.slice(0, -1)) } : undefined,
    next: list.data?.next_after_id ? () => { setSelected(''); setConsent(''); setCursors([...cursors, list.data!.next_after_id!]) } : undefined,
  }
}

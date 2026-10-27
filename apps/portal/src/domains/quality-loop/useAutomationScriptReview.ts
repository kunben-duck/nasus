import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { automationScriptApi } from './automationScriptApi'
import { newScriptDecisions, scriptDecisionsValid, scriptReason } from './automationScriptReviewValidation'
import type { ScriptArchive, ScriptActionDecision, ScriptOracleDecision, ScriptReviewRequest, ScriptDecision } from './types/automationScripts'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useAutomationScriptReview(draft: ScriptArchive, sessionId: string, onFailure: () => void) {
  const [open, setOpen] = useState(false), [selected, setSelected] = useState(''), [editing, setEditing] = useState(false)
  const [decision, setDecision] = useState<'review' | 'withdraw'>('review'), [reason, setReason] = useState(''), [consent, setConsent] = useState('')
  const [actions, setActions] = useState<ScriptActionDecision[]>([]), [assertions, setAssertions] = useState<ScriptOracleDecision[]>([])
  const submitted = useRef(false), m = draft.metadata
  const prefix = ['automation-script-reviews', m.project_id, m.script_revision_id, sessionId, m.artifact_hash]
  const query = useQuery({ ...sensitive, enabled: open, queryKey: prefix, queryFn: ({ signal }) => automationScriptApi.inspect(draft, signal) })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const revision = view?.history.find((item) => item.revision_id === selected)
  const archive = useQuery({ ...sensitive, enabled: open && !!revision, queryKey: [...prefix, selected],
    queryFn: ({ signal }) => automationScriptApi.readReview(draft, revision!, signal) })
  const initialize = useMutation({ retry: false, mutationFn: () => newScriptDecisions(draft), onSuccess: (value) => { setActions(value.actions); setAssertions(value.assertions) } })
  const write = useMutation({ retry: false, mutationFn: ({ input, attempt }: { input: ScriptReviewRequest; attempt: string }) => automationScriptApi.review(input, attempt),
    onSuccess: () => { setEditing(false); setActions([]); setAssertions([]); setReason('') }, onSettled: () => { setConsent(''); void query.refetch() } })
  const failed = query.isError || archive.isError
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = query.isFetching || archive.isFetching || initialize.isPending || write.isPending
  const content = view && !archive.isFetching && !archive.isError ? selected ? archive.data : view.head : undefined
  const consentKey = JSON.stringify([m, query.dataUpdatedAt, view?.head?.revision, decision, actions, assertions, reason])
  const confirmed = !!view && consent === consentKey
  const canSubmit = editing && !selected && !busy && !!view?.can_review && confirmed && scriptReason(reason) && write.isIdle
    && (decision === 'withdraw' ? view.head?.revision.status === 'reviewed' : view.input_current && initialize.isSuccess && scriptDecisionsValid(actions, assertions))
  return { open, view, content, selected, editing, decision, actions, assertions, reason, busy, confirmed, canSubmit, write, failed,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    reload: () => { if (!write.isPending) { setConsent(''); write.reset(); submitted.current = false; void query.refetch(); if (revision) void archive.refetch() } },
    choose: (id: string) => { if (!busy) { setSelected(id); setEditing(false); setConsent('') } },
    begin: (withdraw = false) => { if (!busy && view?.can_review && (withdraw ? view.head?.revision.status === 'reviewed' : view.input_current)) {
      submitted.current = false; setSelected(''); setConsent(''); setReason(''); write.reset(); initialize.reset();
      setDecision(withdraw ? 'withdraw' : 'review'); setEditing(true); setActions([]); setAssertions([]); if (!withdraw) initialize.mutate()
    } },
    editAction: (index: number, changes: { decision: ScriptDecision; reason: string }) => { if (!busy && write.isIdle) { setConsent(''); setActions(actions.map((item, i) => i === index ? { ...item, ...changes } : item)) } },
    editOracle: (index: number, changes: { decision: ScriptDecision; reason: string }) => { if (!busy && write.isIdle) { setConsent(''); setAssertions(assertions.map((item, i) => i === index ? { ...item, ...changes } : item)) } },
    explain: (text: string) => { setConsent(''); setReason(text) },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    submit: () => { if (canSubmit && view && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ attempt: crypto.randomUUID(),
      input: { project_id: m.project_id, script_revision_id: m.script_revision_id, script_artifact_hash: m.artifact_hash,
        expected_previous_revision_id: view.head?.revision.revision_id ?? null, decision, reason, policy_revision: 'nasus.automation-script-review.v1',
        actions: decision === 'review' ? actions : null, assertions: decision === 'review' ? assertions : null } }) } },
  }
}

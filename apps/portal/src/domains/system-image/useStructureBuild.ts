import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ToolInvocation } from '../platform/types/tool'
import { structureBuildApi, type StructureCommandPin } from './structureBuildApi'
import { useStructureCommandDiscovery } from './useStructureCommandDiscovery'
import { useStructureCancellation } from './useStructureCancellation'
import type { BuildPlan } from './types/buildPlan'
import type { ImageReadScope } from './useImageRevisions'

interface Attempt { scope: string; input: StructureCommandPin; command: ToolInvocation | null; commandId: string | null }
const terminal = (command: ToolInvocation | null | undefined) => Boolean(command && ['completed', 'failed', 'cancelled'].includes(command.status))

export function useStructureBuild(scope: ImageReadScope, plan: BuildPlan) {
  const client = useQueryClient()
  const identity = JSON.stringify([scope.projectId, scope.sessionId, plan.plan_id, plan.plan_digest])
  const discovery = useStructureCommandDiscovery(scope, plan)
  const fixedTarget = plan.proposal.intent.target?.target_baseline_id
  const [target, chooseTarget] = useState(fixedTarget ?? '')
  const [saved, setSaved] = useState<Attempt | null>(null)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState(false)
  const attempt = useRef<Attempt | null>(null)
  const inFlight = useRef(false)
  const selected = saved?.scope === identity ? saved : null
  const queryKey = ['system-image', scope.projectId, 'structure-command', scope.sessionId, selected?.commandId] as const
  const observed = useQuery({
    queryKey, enabled: Boolean(selected?.commandId), staleTime: 0, gcTime: 0, retry: false,
    refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => structureBuildApi.read(selected!.input, selected!.commandId!, signal),
    refetchInterval: (query) => !query.state.error && ['pending', 'running'].includes(query.state.data?.status ?? selected?.command?.status ?? '') ? 1000 : false,
  })
  const statusFailed = observed.isError || discovery.failed
  const current = statusFailed ? null : observed.data ?? selected?.command
  const cancellation = useStructureCancellation(scope, selected?.input ?? null, current)
  const running = current?.status === 'pending' || current?.status === 'running'
  const invocation = current?.status === 'waiting_confirmation' ? current.id : ''
  const awaitingDiscovery = !selected && discovery.items.length > 0
  const locked = sending || statusFailed || discovery.checking || awaitingDiscovery || Boolean(selected && !terminal(current))
  function restore(id: string) {
    if (!discovery.ready || selected || inFlight.current) return
    const item = discovery.items.find((row) => row.invocation_id === id)
    if (!item || (fixedTarget && item.target_baseline_id !== fixedTarget)) return
    const restored: Attempt = { scope: identity, input: { project_id: scope.projectId, plan_id: plan.plan_id,
      plan_digest: plan.plan_digest, target_baseline_id: item.target_baseline_id,
      ...(item.idempotency_key === null ? {} : { idempotency_key: item.idempotency_key }) }, commandId: id, command: null }
    attempt.current = restored
    chooseTarget(item.target_baseline_id); setSaved(restored); setFailed(false)
  }
  useEffect(() => {
    if (!selected && discovery.ready && discovery.items.length === 1 && !discovery.hasMore) restore(discovery.items[0].invocation_id)
  })
  useEffect(() => {
    if (current?.status === 'completed') {
      void client.invalidateQueries({ queryKey: ['system-image-build-plans', scope.projectId] })
      void client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'image-revisions'] })
      void client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'structure-discovery'] })
    }
  }, [client, current?.id, current?.status, scope.projectId])
  function setTarget(value: string) {
    if (inFlight.current || locked || fixedTarget) return
    chooseTarget(value)
    attempt.current = null
    setSaved(null)
    setFailed(false)
  }
  async function execute() {
    if (inFlight.current || cancellation.busy || running || statusFailed || discovery.checking || awaitingDiscovery || observed.isFetching
        || (selected?.commandId && !current) || current?.status === 'waiting_approval' || !target) return
    inFlight.current = true
    setSending(true); setFailed(false)
    try {
      let original = attempt.current
      if (!original || original.scope !== identity || terminal(current)) {
        original = { scope: identity, input: { project_id: scope.projectId, plan_id: plan.plan_id,
          plan_digest: plan.plan_digest, target_baseline_id: target, idempotency_key: crypto.randomUUID() }, command: null, commandId: null }
        attempt.current = original
        setSaved(original)
      }
      const result = invocation ? await structureBuildApi.confirm(original.input, invocation)
        : await structureBuildApi.prepare({ ...original.input, idempotency_key: original.input.idempotency_key! })
      const updated = { ...original, command: result, commandId: result.id }
      attempt.current = updated
      client.setQueryData(['system-image', scope.projectId, 'structure-command', scope.sessionId, result.id], result)
      setSaved(updated)
    } catch {
      setFailed(true)
      if (attempt.current?.commandId) void observed.refetch()
    } finally { inFlight.current = false; setSending(false) }
  }
  return { target, setTarget, invocation, running, locked: locked || Boolean(fixedTarget), busy: sending || running || cancellation.busy, cancellation,
    checking: observed.isFetching || discovery.checking, statusFailed,
    reloadStatus: () => discovery.failed ? discovery.reload() : observed.refetch(),
    unfinished: selected || discovery.failed ? [] : discovery.items, restore,
    more: discovery.more, hasMore: !selected && discovery.hasMore,
    unacknowledged: failed && !running && !terminal(current),
    failed: current?.status === 'failed', cancelled: current?.status === 'cancelled', execute }
}

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { buildPlanApi } from '../../../../../domains/system-image/buildPlanApi'
import type { BuildPlan } from '../../../../../domains/system-image/types/buildPlan'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { BuildPlanPhaseAction } from './BuildPlanPhaseAction'

const sensitiveRead = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }

export function BuildPlanRevisionAction({ scope, plan, manifestId }: { scope: ImageReadScope; plan: BuildPlan; manifestId?: string }) {
  const { t } = useI18n()
  const [opened, setOpened] = useState(false)
  const [goalId, setGoalId] = useState('')
  const [checked, setChecked] = useState(false)
  const [commandId, setCommandId] = useState('')
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const goals = useQuery({ ...sensitiveRead, enabled: opened,
    queryKey: ['system-image-build-plans', scope.projectId, scope.sessionId, plan.plan_id, 'revision-goals'],
    queryFn: ({ signal }) => buildPlanApi.revisionGoals(scope.projectId, plan.plan_id, signal) })
  const checkpoint = useQuery({ ...sensitiveRead, enabled: opened && !!goalId,
    queryKey: ['system-image-build-plans', scope.projectId, scope.sessionId, plan.plan_id, 'revision-checkpoint', goalId],
    queryFn: ({ signal }) => buildPlanApi.revisionCheckpoint(scope.projectId, plan.plan_id, goalId, signal) })
  useEffect(() => { if (goals.isError || checkpoint.isError) scope.onFailure(true) }, [goals.isError, checkpoint.isError, scope])
  useEffect(() => { setChecked(false); setCommandId('') }, [goalId, manifestId, checkpoint.data])
  const latestManifest = checkpoint.data?.history.at(-1)?.revision.source_manifest_id ?? plan.proposal.intent.source_manifest_id
  const checking = goals.isFetching || checkpoint.isFetching
  const disabled = busy || checking || !checkpoint.data || !manifestId || manifestId === latestManifest
    || !['structural_candidate_review', 'build_completion_review'].includes(checkpoint.data.goal.pause_reason ?? '')
  async function save() {
    if (inFlight.current || disabled || !checked || !checkpoint.data || !manifestId) return
    inFlight.current = true
    setBusy(true)
    try {
      const command = commandId ? await buildPlanApi.confirmRevision(commandId)
        : await buildPlanApi.prepareRevision(plan, manifestId, checkpoint.data, crypto.randomUUID())
      if (command.tool_id !== 'system_image.build.plan.revise') throw new Error('Revision command mismatch')
      if (command.status === 'waiting_confirmation' && !commandId) setCommandId(command.id)
      else if (command.status === 'completed' && commandId) {
        setChecked(false)
        setCommandId('')
        await checkpoint.refetch({ throwOnError: true })
      } else throw new Error('Revision outcome could not be verified')
    } catch {
      setChecked(false)
      setCommandId('')
      scope.onFailure(true)
    } finally { inFlight.current = false; setBusy(false) }
  }
  return <details onToggle={(event) => setOpened(event.currentTarget.open)}>
    <summary>{t('Revise with captured sources')}</summary>
    {opened && <div className="build-plan-form structure-build-action">
      <p>{t('Keep the original goal and source pins. Save a revised draft only; execution needs new authorization.')}</p>
      <label>{t('Original paused build goal')}<select value={goalId} disabled={busy || checking || !!commandId}
        onChange={(event) => setGoalId(event.target.value)}>
        <option value="">{t('Choose the original build goal')}</option>
        {(goals.data ?? []).map((goal) => <option key={goal.goal_id} value={goal.goal_id}>{goal.title} · {goal.goal_id}</option>)}
      </select></label>
      {checking && <p role="status">{t('Checking source access...')}</p>}
      {!goals.isPending && !goals.data?.length && <p>{t('No paused build goal is available for this plan.')}</p>}
      {checkpoint.data && !checking && <>
        <p>{t('Source manifest')}{' '}<code>{manifestId ?? t('Unavailable')}</code></p>
        <label className="structure-stop-consent"><input type="checkbox" checked={checked} disabled={disabled || !!commandId}
          onChange={(event) => setChecked(event.target.checked)} />{t('Save a revised draft without resuming or executing the goal')}</label>
        {commandId && <p role="status">{t('Confirm this exact plan revision. No execution grant will be transferred.')}</p>}
        <button type="button" disabled={disabled || !checked} onClick={() => void save()}>
          {t(busy ? 'Saving draft...' : commandId ? 'Confirm plan revision' : 'Prepare plan revision')}</button>
        <h3>{t('Same-goal plan revisions')}</h3>
        <ol className="image-revision-rows">{checkpoint.data.history.map((item) => <li key={item.revision.revision_id}>
          <strong>{t('Draft only')} · {item.revision.revision_number}</strong>
          <p>{item.revision.plan_id}</p><p>{item.revision.source_manifest_id}</p><p>{item.revision.created_at}</p>
        </li>)}</ol>
      </>}
      {checkpoint.data && checkpoint.data.history.length > 0 && <BuildPlanPhaseAction scope={scope} plan={plan} checkpoint={checkpoint.data}
        checking={checking} reload={() => checkpoint.refetch({ throwOnError: true })} />}
    </div>}
  </details>
}

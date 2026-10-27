import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import type { AgentGoal } from '../../../../../domains/agent/types'
import type { BuildPlan, BuildPlanRevision } from '../../../../../domains/system-image/types/buildPlan'
import { buildPlanPhaseApi } from '../../../../../domains/system-image/buildPlanPhaseApi'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function BuildPlanPhaseAction({ scope, plan, checkpoint, checking, reload }: {
  scope: ImageReadScope; plan: BuildPlan; checkpoint: { goal: AgentGoal; history: BuildPlanRevision[] }; checking: boolean; reload: () => Promise<unknown>
}) {
  const { t } = useI18n()
  const [opened, setOpened] = useState(false)
  const [checked, setChecked] = useState(false)
  const [commandId, setCommandId] = useState('')
  const [seconds, setSeconds] = useState(Math.min(1200, plan.proposal.intent.budget.max_active_seconds))
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const phases = useQuery({ enabled: opened && !checking, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryKey: ['system-image-build-plans', scope.projectId, scope.sessionId, plan.plan_id, 'phases', checkpoint.goal.id, checkpoint.goal.steps.length, checkpoint.goal.pause_reason],
    queryFn: ({ signal }) => buildPlanPhaseApi.history(plan, checkpoint.goal, checkpoint.history, signal) })
  useEffect(() => { if (phases.isError) scope.onFailure(true) }, [phases.isError, scope])
  useEffect(() => { setChecked(false); setCommandId('') }, [checkpoint, phases.data, seconds])
  const latest = checkpoint.history.at(-1), parent = phases.data?.phases.at(-1)
  const prepared = checkpoint.goal.pause_reason === 'build_plan_phase_prepared'
  const disabled = busy || checking || phases.isFetching || !phases.data || !latest || prepared
    || latest.revision.plan_id === parent?.phase.plan_id
  async function prepareOrConfirm() {
    if (lock.current || disabled || !checked || !phases.data) return
    lock.current = true
    setBusy(true)
    try {
      const command = commandId ? await buildPlanPhaseApi.confirm(commandId, phases.data)
        : await buildPlanPhaseApi.prepare(plan, phases.data, seconds, crypto.randomUUID())
      if (command.tool_id !== 'system_image.build.plan.activate_revision') throw new Error('Phase command mismatch')
      if (!commandId && command.status === 'waiting_confirmation') setCommandId(command.id)
      else if (commandId && command.status === 'completed') {
        setCommandId('')
        setChecked(false)
        await reload()
      } else throw new Error('Phase command could not be acknowledged')
    } catch {
      setChecked(false)
      setCommandId('')
      scope.onFailure(true)
    } finally { lock.current = false; setBusy(false) }
  }
  return <details onToggle={(event) => setOpened(event.currentTarget.open)}>
    <summary>{t('Continue with revised sources')}</summary>
    {opened && !checking && <div className="build-plan-form structure-build-action">
      <p>{t('Append a new phase to the original goal. Historical work is preserved; execution requires separate consent.')}</p>
      {phases.isFetching && <p role="status">{t('Checking source access...')}</p>}
      {phases.data && !phases.isFetching && <>
        {prepared ? <>
          <p role="status">{t('Revised phase prepared. The goal is still paused.')}</p>
          <Link to={`/projects/${encodeURIComponent(scope.projectId)}`}>{t('Review execution confirmation')}</Link>
        </> : <>
          <label>{t('Active time limit (seconds)')}<input type="number" min={1} max={plan.proposal.intent.budget.max_active_seconds}
            value={seconds} disabled={busy || !!commandId} onChange={(event) => setSeconds(Number(event.target.value))} /></label>
          <p>{t('This phase proposes one structural build, zero model calls and zero model cost. It does not reset the goal budget.')}</p>
          <label className="structure-stop-consent"><input type="checkbox" checked={checked} disabled={disabled || !!commandId}
            onChange={(event) => setChecked(event.target.checked)} />{t('Prepare the revised phase without executing it')}</label>
          <button type="button" disabled={disabled || !checked || !Number.isInteger(seconds) || seconds < 1
            || seconds > plan.proposal.intent.budget.max_active_seconds} onClick={() => void prepareOrConfirm()}>
            {t(busy ? 'Preparing phase...' : commandId ? 'Confirm revised phase' : 'Prepare revised phase')}</button>
        </>}
        <h3>{t('Original-goal plan phases')}</h3>
        <ol className="image-revision-rows">{phases.data.phases.map(({ phase }) => <li key={phase.phase_id}>
          <strong>{t('Phase')} {phase.phase_number}</strong><p>{phase.plan_id}</p><p>{phase.source_manifest_id}</p>
        </li>)}</ol>
      </>}
    </div>}
  </details>
}

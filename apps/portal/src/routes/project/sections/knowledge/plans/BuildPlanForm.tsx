import { useRef, useState } from 'react'
import { buildPlanApi } from '../../../../../domains/system-image/buildPlanApi'
import type { BuildPlanInput } from '../../../../../domains/system-image/types/buildPlan'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { BaselineRecord } from '../../../../../domains/system-image/types/baseline'
import { useBuildTarget } from '../../../../../domains/system-image/useBuildTarget'

export function BuildPlanForm({ scope, manifestId, baselines, saved, cancel }: {
  scope: ImageReadScope; manifestId: string; baselines: BaselineRecord[]; saved: (id: string) => void; cancel: () => void
}) {
  const { t } = useI18n()
  const [objective, setObjective] = useState('')
  const [purpose, setPurpose] = useState<BuildPlanInput['purpose']>('structure')
  const [mode, setMode] = useState<BuildPlanInput['mode']>('initialize')
  const [cost, setCost] = useState('')
  const [pending, setPending] = useState(false)
  const [tools, setTools] = useState('80')
  const [models, setModels] = useState('30')
  const [seconds, setSeconds] = useState('1200')
  const [baselineId, setBaselineId] = useState('')
  const target = useBuildTarget(scope, baselineId)
  const verifiedTarget = !target.isError && !target.isFetching ? target.data : undefined
  const attempt = useRef({ fingerprint: '', key: '' })
  return <form className="build-plan-form" onSubmit={async (event) => {
    event.preventDefault()
    if (pending || !objective.trim() || !verifiedTarget) return
    setPending(true)
    const input: BuildPlanInput = { project_id: scope.projectId, source_manifest_id: manifestId, objective: objective.trim(),
      mode, purpose, target: verifiedTarget, budget: { max_tool_calls: Number(tools), max_model_calls: Number(models),
        max_active_seconds: Number(seconds), max_cost_microusd: cost === '' ? null : Math.round(Number(cost) * 1_000_000) } }
    const fingerprint = JSON.stringify(input)
    if (fingerprint !== attempt.current.fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() }
    try { saved(await buildPlanApi.propose(input, attempt.current.key)) }
    catch { scope.onFailure(true) }
    finally { setPending(false) }
  }}>
    <p className="evidence-revision">{t('Source manifest')}<code>{manifestId}</code></p>
    <p>{t('Code is required. Requirements and historical tests are optional; missing evidence remains an explicit gap.')}</p>
    <label>{t('Build intent target')}<select value={baselineId} required disabled={pending} onChange={(event) => setBaselineId(event.target.value)}>
      <option value="">{t('Select a target baseline')}</option>
      {baselines.filter((item) => item.project_id === scope.projectId).map((item) => <option key={item.id} value={item.id}>{item.kind} · {item.id}</option>)}
    </select></label>
    {baselineId && target.isFetching && <p role="status">{t('Checking build target...')}</p>}
    {target.isError && <><p role="alert">{t('Build target could not be verified. Reload before saving; no target is selected automatically.')}</p>
      <button type="button" disabled={pending || target.isFetching} onClick={() => void target.refetch()}>{t('Reload build target')}</button></>}
    {verifiedTarget && <p className="evidence-revision">{t('Pinned target version')}<code>{verifiedTarget.target_version_id ?? t('None')}</code>
      {t('Expected publication head')}<code>{verifiedTarget.expected_head_id ?? t('None')}</code></p>}
    <label>{t('Investigation objective')}<textarea required maxLength={2000} value={objective} disabled={pending}
      onChange={(event) => setObjective(event.target.value)} /></label>
    <label>{t('Investigation mode')}<select value={mode} disabled={pending}
      onChange={(event) => setMode(event.target.value as BuildPlanInput['mode'])}>
      <option value="initialize">{t('Initialize')}</option><option value="enrich">{t('Enrich')}</option>
      <option value="refresh">{t('Refresh')}</option><option value="repair">{t('Repair')}</option></select></label>
    <label>{t('Investigation purpose')}<select value={purpose} disabled={pending}
      onChange={(event) => setPurpose(event.target.value as BuildPlanInput['purpose'])}>
      <option value="structure">{t('Structure')}</option><option value="behavior">{t('Behavior')}</option>
      <option value="traceability">{t('Traceability')}</option></select></label>
    <div className="build-plan-budget">
      <label>{t('Tool call limit')}<input type="number" min={purpose === 'structure' ? 2 : 3} max={1000} step={1} required value={tools} disabled={pending} onChange={(event) => setTools(event.target.value)} /></label>
      <label>{t('Model call limit')}<input type="number" min={1} max={1000} step={1} required value={models} disabled={pending} onChange={(event) => setModels(event.target.value)} /></label>
      <label>{t('Active time limit (seconds)')}<input type="number" min={1} max={86400} step={1} required value={seconds} disabled={pending} onChange={(event) => setSeconds(event.target.value)} /></label>
    </div>
    <label>{t('Proposed cost ceiling (USD, optional)')}<input type="number" min={0} max={1000} step={0.000001}
      value={cost} disabled={pending} onChange={(event) => setCost(event.target.value)} /></label>
    <p>{t('Budgets are proposals, not grants. Model cost and execution scope still require authorization.')}</p>
    <div className="analysis-toolbar"><button type="button" disabled={pending} onClick={cancel}>{t('Cancel')}</button>
      <button type="submit" disabled={pending || !objective.trim() || !verifiedTarget}>{t(pending ? 'Saving draft...' : 'Save investigation draft')}</button></div>
  </form>
}

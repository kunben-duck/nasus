import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useBuildPlans } from '../../../../../domains/system-image/useBuildPlans'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { BuildPlanForm } from './BuildPlanForm'
import { BuildPlanDetails } from './BuildPlanDetails'
import type { BaselineRecord } from '../../../../../domains/system-image/types/baseline'

export function BuildPlanSelector({ scope, manifestId, baselines }: { scope: ImageReadScope; manifestId?: string; baselines: BaselineRecord[] }) {
  const { t } = useI18n()
  const client = useQueryClient()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const [adding, setAdding] = useState<string | null>(null)
  const query = useBuildPlans(scope, cursors.at(-1)!)
  if (query.isError) return null
  if (query.isPending) return <p role="status">{t('Checking source access...')}</p>
  const move = (next: string[]) => { setChosen(''); setAdding(null); setCursors(next) }
  return <>
    {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    <div hidden={query.isFetching}>
    <div className="analysis-toolbar"><p>{t('Plans preserve their source revisions even when current sources change.')}</p>
      <button type="button" disabled={!manifestId} onClick={() => { setAdding(manifestId ?? null); setChosen('') }}>{t('Propose investigation')}</button></div>
    {!manifestId && <p>{t('Capture sources before proposing a plan.')}</p>}
    {adding ? <BuildPlanForm scope={scope} manifestId={adding} baselines={baselines} cancel={() => setAdding(null)}
      saved={(id) => { setAdding(null); setChosen(id); void client.invalidateQueries({ queryKey: ['system-image-build-plans', scope.projectId] }) }} />
      : <>
        <label className="evidence-selector">{t('Saved investigation plan')}
          <select value={query.data.items.some((item) => item.plan_id === chosen) ? chosen : ''} onChange={(event) => setChosen(event.target.value)}>
            <option value="">{t('Choose an investigation plan')}</option>
            {query.data.items.map((item) => <option key={item.plan_id} value={item.plan_id}>{item.created_at.slice(0, 19).replace('T', ' ')} · {item.plan_id.slice(0, 8)} · {item.purpose}</option>)}
          </select>
        </label>
        {!query.data.items.length && <p>{t('No investigation plans are available to you.')}</p>}
        <AnalysisPagination label={t('Investigation plan pages')} page={cursors.length}
          previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
          next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
        {chosen && <BuildPlanDetails key={chosen} scope={scope} planId={chosen} baselines={baselines} manifestId={manifestId} />}
      </>}
    </div>
  </>
}

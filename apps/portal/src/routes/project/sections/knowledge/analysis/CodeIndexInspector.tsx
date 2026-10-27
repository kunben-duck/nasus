import { useState } from 'react'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { AnalysisReadScope } from '../../../../../domains/system-image/useCodeAnalysis'
import { useCodeIndexList, useCodeIndexStatus } from '../../../../../domains/system-image/useCodeIndexes'
import type { CodeIndexPin } from '../../../../../domains/system-image/types/codeIndex'
import { AnalysisPagination } from './AnalysisPagination'

const stateLabels = { idle: 'Idle', preparing: 'Preparing', ready: 'Ready', degraded: 'Partial',
  cancel_requested: 'Cancellation requested', cancelled: 'Cancelled', failed: 'Failed' }
const workerLabels = { none: 'No active worker', active: 'Active worker', expired: 'Worker lease expired' }
const outcomeLabels = { cancel_requested: 'Cancellation requested', cancelled: 'Cancelled',
  already_committed: 'Image already committed; existing facts were retained.', already_terminal: 'The original command has already stopped.' }

function IndexStatus({ scope, pin }: { scope: AnalysisReadScope; pin: CodeIndexPin }) {
  const { t, tx } = useI18n()
  const state = useCodeIndexStatus(scope, pin)
  if (state.query.isError) return null
  if (!state.view) return <p role="status">{t('Checking source access...')}</p>
  const view = state.view.status
  return <section data-testid="code-index-status">
    <dl>
      <dt>{t('Captured code revision')}</dt><dd><code>{pin.source_revision_id}</code></dd>
      <dt>{t('Original command')}</dt><dd><code>{pin.invocation_id}</code> · {tx(view.invocation_status)}</dd>
      <dt>{t('Native index state')}</dt><dd>{tx(stateLabels[view.state])} · {tx(workerLabels[view.worker_state])}</dd>
      <dt>{t('Worker epoch')}</dt><dd>{view.epoch}</dd>
      <dt>{t('Observed at')}</dt><dd>{view.observed_at}</dd>
      <dt>{t('Entity enumeration')}</dt><dd>{view.entity_count ?? t('Unknown')}</dd>
      <dt>{t('Relationship enumeration')}</dt><dd>{view.relationship_count ?? t('Unknown')}</dd>
      {view.provider_version && <><dt>{t('Provider')}</dt><dd>{view.provider_version}</dd></>}
      {!!view.protocol?.gaps.length && <><dt>{t('Projection gaps')}</dt><dd><ul>{view.protocol.gaps.map((gap) =>
        <li key={gap}><code>{gap}</code></li>)}</ul></dd></>}
    </dl>
    <button type="button" className="small-btn" disabled={state.write.isPending} onClick={state.reload}>{t('Refresh index status')}</button>
    {state.view.can_cancel && <div>
      <label><input type="checkbox" checked={state.confirmed} disabled={state.write.isPending}
        onChange={(event) => state.confirm(event.target.checked)} />{t('I confirm cancellation of this index build. Committed image facts will not be removed.')}</label>
      <button type="button" className="small-btn" disabled={!state.canCancel} onClick={state.cancel}>{t('Cancel index build')}</button>
    </div>}
    {state.write.isPending && <p role="status">{t('Requesting index cancellation...')}</p>}
    {state.write.data && <p role="status">{tx(outcomeLabels[state.write.data.outcome])}</p>}
  </section>
}

export function CodeIndexInspector({ scope, bindingId }: { scope: AnalysisReadScope; bindingId: string }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false), [cursors, setCursors] = useState(['']), [chosen, setChosen] = useState('')
  const query = useCodeIndexList(scope, bindingId, cursors.at(-1)!, open)
  const pin = !query.isError ? query.data?.items.find((item) => item.generation_id === chosen) : undefined
  const move = (next: string[]) => { setChosen(''); setCursors(next) }
  return <details className="evidence-integrity-details" data-testid="code-index-inspector"
    onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{t('Code index history for this source')}</summary>
    <p>{t('Each index retains its own captured revision. Status reads do not start a provider or approve business behavior.')}</p>
    {open && <>
      {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
      {!query.isPending && !query.isError && <div hidden={query.isFetching}>
        <label className="evidence-selector">{t('Code index generation')}
          <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
            <option value="">{t('Choose a code index')}</option>
            {query.data.items.map((item) => <option key={item.generation_id} value={item.generation_id}>
              {item.generation_id} · {item.source_revision_id}
            </option>)}
          </select>
        </label>
        {!query.data.items.length && <p>{t('No durable code indexes have been recorded for this source.')}</p>}
        <AnalysisPagination page={cursors.length} previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
          next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
        {pin && <IndexStatus key={pin.generation_id} scope={scope} pin={pin} />}
      </div>}
    </>}
  </details>
}

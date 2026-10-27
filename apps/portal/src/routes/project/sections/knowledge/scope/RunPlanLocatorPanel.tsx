import { useState } from 'react'
import { useRunPlanLocators } from '../../../../../domains/quality-loop/useRunPlanLocators'
import type { LocatorStatus } from '../../../../../domains/quality-loop/types/runPlanLocators'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../../../shared/i18n/messages'

const labels: Record<LocatorStatus, MessageKey> = { static_match: 'Static method and path match', ambiguous: 'Multiple matching declarations',
  unresolved: 'Additional routing conditions remain unresolved', not_found: 'No matching declaration found', unsupported: 'Locator analysis not supported' }
export function RunPlanLocatorPanel({ plan, actorId, onFailure }: { plan: RunPlanArchive; actorId: string; onFailure: () => void }) {
  const { t } = useI18n(), state = useRunPlanLocators(plan, actorId, onFailure)
  const [page, setPage] = useState(0), [inventoryOpen, setInventoryOpen] = useState(false)
  const items = state.value?.report.locators ?? [], offset = Math.min(page * 20, Math.max(0, Math.floor((items.length - 1) / 20) * 20))
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Frozen-source request locators')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect request source locators')}</button>
    {state.open && <>
      <p>{t('Analyze every original request against frozen source bytes. Static paths do not verify runtime routing, fixtures, execution or business coverage.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Recheck frozen-source locators')}</button>
      {state.busy && <p role="status">{t('Checking original source pins and request locators...')}</p>}
      {state.failed && <p role="alert">{t('Original locator evidence could not be verified. Protected content is hidden.')}</p>}
      {state.value && <div className="scope-record" data-testid="run-plan-locators">
        <strong>{t('Static evidence only; execution remains unauthorized')}</strong>
        <code>{state.value.receipt.report_hash}</code>
        <p>{t('{count} original actions inspected; executed and passed counts remain zero.', { count: state.value.report.summary.locator_count })}</p>
        <ul className="run-plan-locator-list">{items.slice(offset, offset + 20).map((item) => <li key={`${item.case_id}:${item.action_index}`}>
          <code>{item.case_id}</code><span>{t('Original action')} {item.action_index + 1}</span>
          {item.request_id && <code>{item.request_id}: {item.method} {item.path}</code>}
          <strong>{t(labels[item.status])}</strong>
          <details><summary>{t('Inspect original locator metadata')}</summary><code>{item.action_digest}</code><code>{item.reason}</code>
            {item.candidates.map((candidate, index) => <div className="scope-record" key={index}>
              <code>{candidate.binding_id}</code><code>{candidate.source_revision_id}</code>
              <code>{candidate.relative_path}:{candidate.start_line}-{candidate.end_line}</code>
              <code>{candidate.method} {candidate.route_path}</code><code>{candidate.source_file_hash}</code><code>{candidate.snippet_hash}</code>
              {candidate.supporting_spans.map((span, offset) => <p key={offset}><span>{t(span.role === 'controller' ? 'Controller declaration' : 'Class-level route declaration')}</span>
                <code>{candidate.relative_path}:{span.start_line}-{span.end_line}</code><code>{span.snippet_hash}</code></p>)}
            </div>)}
          </details>
        </li>)}</ul>
        {items.length > 20 && <div className="scope-record"><span>{t('Original action')} {offset + 1}-{Math.min(offset + 20, items.length)} / {items.length}</span>
          <button type="button" className="small-btn" disabled={offset === 0} onClick={() => setPage(offset / 20 - 1)}>{t('Previous page')}</button>
          <button type="button" className="small-btn" disabled={offset + 20 >= items.length} onClick={() => setPage(offset / 20 + 1)}>{t('Next page')}</button>
        </div>}
        <details onToggle={(event) => setInventoryOpen(event.currentTarget.open)}><summary>{t('Inspect complete frozen route inventory')}</summary>
          {inventoryOpen && <pre>{JSON.stringify(state.value.report.inventory, null, 2)}</pre>}
        </details>
      </div>}
    </>}
  </section>
}

import { useMappingStaging } from '../../../../../domains/quality-loop/useMappingStaging'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { MappingPartEditor } from './MappingPartEditor'
import { MappingFinalizationPanel } from './MappingFinalizationPanel'

export function MappingStagingPanel({ draft, previous, scopeCurrent, sessionId, onFailure, onDone }: {
  draft: GenerationArchive; previous: string | null; scopeCurrent: boolean; sessionId: string; onFailure: () => void; onDone: () => void
}) {
  const { t } = useI18n(), state = useMappingStaging(draft, previous, scopeCurrent, sessionId, onFailure), workspace = state.workspace
  return <section className="mapping-staging" aria-label={t('Partitioned assertion review')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.partBusy || state.finalBusy} onClick={state.toggle}>{t('Review mapping in parts')}</button>
    {state.open && <>
      <p>{t('Save private decisions in bounded parts, then independently confirm the complete set. No assertions are omitted.')}</p>
      <button type="button" className="small-btn" disabled={state.partBusy || state.finalBusy} onClick={state.reload}>{t('Reload partition plan')}</button>
      {state.query.isFetching && <p role="status">{t('Verifying the complete partition plan...')}</p>}
      {workspace && <>
        <p>{t('{parts} parts preserve all {assertions} assertion pairs across {cases} cases.', {
          parts: workspace.plan.part_count, assertions: workspace.plan.assertion_count, cases: workspace.plan.case_count })}</p>
        <code>{workspace.plan.plan_digest}</code>
        {!!workspace.plan.part_count && <>
          <div className="scope-actions"><button type="button" className="small-btn" disabled={state.partBusy || state.finalBusy || state.sequence === 0} onClick={() => state.choose(state.sequence - 1)}>{t('Previous part')}</button>
            <button type="button" className="small-btn" disabled={state.partBusy || state.finalBusy || state.sequence + 1 >= workspace.plan.part_count} onClick={() => state.choose(state.sequence + 1)}>{t('Next part')}</button></div>
          <MappingPartEditor key={`${workspace.plan.plan_digest}:${state.sequence}:${state.query.dataUpdatedAt}`} draft={draft} workspace={workspace}
            sequence={state.sequence} disabled={state.finalBusy} onFailure={onFailure} onChange={state.invalidate} onBusy={state.setPartBusy} />
          <MappingFinalizationPanel key={`${workspace.plan.plan_digest}:${state.changed}`} workspace={workspace} changed={state.changed} disabled={state.partBusy}
            onFailure={onFailure} onDone={() => { state.close(); onDone() }} onBusy={state.setFinalBusy} />
        </>}
      </>}
    </>}
  </section>
}

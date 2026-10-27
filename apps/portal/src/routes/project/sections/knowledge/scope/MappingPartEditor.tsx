import { useEffect } from 'react'
import { useMappingPartEditor } from '../../../../../domains/quality-loop/useMappingPartEditor'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { MappingWorkspace } from '../../../../../domains/quality-loop/types/mappingStaging'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { MappingPartAssertions } from './MappingPartAssertions'

export function MappingPartEditor({ draft, workspace, sequence, disabled, onFailure, onChange, onBusy }: {
  draft: GenerationArchive; workspace: MappingWorkspace; sequence: number; disabled: boolean
  onFailure: () => void; onChange: () => void; onBusy: (busy: boolean) => void
}) {
  const { t } = useI18n(), state = useMappingPartEditor(draft, workspace, sequence, onFailure, onChange)
  useEffect(() => { onBusy(state.busy || state.editing); return () => onBusy(false) }, [state.busy, state.editing, onBusy])
  const view = state.view, content = state.content
  return <fieldset className="mapping-part-editor" disabled={disabled || state.busy} aria-label={t('Private mapping part')}>
    <legend>{t('Part {part} of {total}', { part: sequence + 1, total: workspace.plan.part_count })}</legend>
    {state.busy && <p role="status">{t('Verifying private part and current source access...')}</p>}
    {state.write.isError && <p role="alert">{t('Part save was not acknowledged. Reload this part before another confirmation; no automatic retry was sent.')}</p>}
    {state.write.isSuccess && <p role="status">{t('Private part saved; final approval still requires all parts and a separate confirmation.')}<code>{state.write.data.invocationId}</code></p>}
    {view && <>
      <code>{view.part.part_digest}</code>
      <p>{t('{count} assertion pairs in this part.', { count: view.part.assertions.length })}</p>
      <label>{t('Private part history')}<select value={state.selected} onChange={(e) => { onChange(); state.choose(e.target.value) }}>
        <option value="">{t('Current private part head')}</option>{view.head.history.map((r) => <option key={r.part_revision_id} value={r.part_revision_id}>{r.revision_sequence} · {r.recorded_at}</option>)}</select></label>
      {view.head.history_truncated && <p>{t('Showing the latest {shown} of {total} private revisions.', { shown: view.head.history.length, total: view.head.history_count })}</p>}
      {content && !state.editing && <div className="scope-record"><code>{content.revision.part_revision_id}</code>
        <p>{content.current_use.part_current ? t('Current private part; not final approval') : t('Historical private part; not current')}</p>
        <MappingPartAssertions key={content.revision.part_revision_id} draft={draft} values={content.request.decisions} readOnly onChange={() => {}} />
      </div>}
      <div className="scope-actions"><button type="button" className="small-btn" disabled={!state.editable} onClick={() => { onChange(); state.begin() }}>{t('Edit this part')}</button>
        <button type="button" className="small-btn" onClick={() => { onChange(); state.reload() }}>{t('Reload private part')}</button></div>
      {state.editing && <fieldset disabled={!state.write.isIdle} aria-label={t('Edit private assertion decisions')}>
        <legend>{t('Edit private assertion decisions')}</legend>
        <MappingPartAssertions draft={draft} values={state.values} onChange={(i, v) => { onChange(); state.edit(i, v) }} />
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(e) => state.confirm(e.target.checked)} />
          {t('I confirm saving every exact assertion in this private part. This does not approve the final mapping.')}</label>
        <button type="button" className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Save private part')}</button>
      </fieldset>}
    </>}
  </fieldset>
}

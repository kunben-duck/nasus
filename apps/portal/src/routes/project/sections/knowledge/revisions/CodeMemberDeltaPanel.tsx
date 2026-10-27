import { useId, useState } from 'react'
import { useImageRevisions, type ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useCodeMemberDelta } from '../../../../../domains/system-image/useCodeMemberDelta'
import { codeMemberKinds, type CodeMemberDeltaPair, type CodeMemberKind } from '../../../../../domains/system-image/types/codeMemberDelta'
import type { ImageRevisionSummary } from '../../../../../domains/system-image/types/imageRevision'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'

const labels: Record<CodeMemberKind, string> = { added_member: 'Added to image', removed_member: 'Removed from image',
  revision_changed: 'Entity revision changed', projection_changed: 'Projection changed', unchanged: 'Unchanged member' }

export function CodeMemberDeltaPanel({ scope, revision }: { scope: ImageReadScope; revision: ImageRevisionSummary }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const id = useId()
  return <section className="code-member-delta-panel">
    <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>{t('Compare code versions')}</button>
    {open && <div id={id}><p>{t('Compare registered code members of two frozen images. Removal is not proof of source deletion; revision changes are not proof of changed behavior. No approvals, coverage or execution permissions are transferred.')}</p>
      <CodeMemberDeltaPicker scope={scope} after={revision} /></div>}
  </section>
}

function CodeMemberDeltaPicker({ scope, after }: { scope: ImageReadScope; after: ImageRevisionSummary }) {
  const { t } = useI18n()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const [before, setBefore] = useState<ImageRevisionSummary | null>(null)
  const query = useImageRevisions(scope, cursors.at(-1)!)
  const selected = query.data?.items.find((item) => item.image_revision_id === chosen)
  const move = (next: string[]) => { setChosen(''); setBefore(null); setCursors(next) }
  return <>
    {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    {query.isError && <p role="alert">{t('Code version comparison could not be verified. Previous results are hidden; reload to check access.')}</p>}
    {!query.isFetching && !query.isError && query.data && <>
      <form aria-label={t('Code version comparison')} onSubmit={(event) => { event.preventDefault(); if (selected && selected.image_revision_id !== after.image_revision_id) setBefore(selected) }}>
        <label>{t('Compare from image')}<select value={chosen} onChange={(event) => { setBefore(null); setChosen(event.target.value) }}>
          <option value="">{t('Choose an image revision')}</option>
          {query.data.items.filter((item) => item.image_revision_id !== after.image_revision_id).map((item) =>
            <option key={item.image_revision_id} value={item.image_revision_id}>{item.recorded_at.slice(0, 19).replace('T', ' ')} · {item.image_revision_id}</option>)}
        </select></label>
        <button type="submit" disabled={!selected || selected.image_revision_id === after.image_revision_id}>{t('Compare fixed images')}</button>
      </form>
      <AnalysisPagination label={t('Comparison image pages')} page={cursors.length}
        previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
        next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
      {before && <CodeMemberDeltaResult key={`${before.image_revision_id}:${before.artifact_hash}:${after.image_revision_id}:${after.artifact_hash}`}
        scope={scope} pair={{ before, after }} />}
    </>}
  </>
}

function CodeMemberDeltaResult({ scope, pair }: { scope: ImageReadScope; pair: CodeMemberDeltaPair }) {
  const { t, tx } = useI18n()
  const [paging, setPaging] = useState<{ kind: CodeMemberKind | null; offsets: number[] }>({ kind: null, offsets: [0] })
  const query = useCodeMemberDelta(scope, pair, { kind: paging.kind, offset: paging.offsets.at(-1)! })
  return <section aria-label={t('Code member comparison results')}>
    <label>{t('Member change category')}<select value={paging.kind ?? ''} onChange={(event) =>
      setPaging({ kind: event.target.value === '' ? null : event.target.value as CodeMemberKind, offsets: [0] })}>
      <option value="">{t('All member changes')}</option>
      {codeMemberKinds.map((kind) => <option key={kind} value={kind}>{tx(labels[kind])}</option>)}
    </select></label>
    {query.isFetching && <p role="status">{t('Verifying fixed code version comparison...')}</p>}
    {query.isError && <p role="alert">{t('Code version comparison could not be verified. Previous results are hidden; reload to check access.')}</p>}
    {!query.isFetching && !query.isError && query.data && <div data-testid="code-member-delta-result">
      <dl className="code-member-delta-counts">{codeMemberKinds.map((kind) => <div key={kind}><dt>{tx(labels[kind])}</dt><dd>{query.data.counts[kind]}</dd></div>)}</dl>
      {query.data.source_scope_changed && <p>{t('Code source scope differs between these images. Missing members must not be interpreted as deleted code.')}</p>}
      <details className="image-source-document"><summary>{t('Comparison provenance')}</summary><dl>
        <div><dt>{t('Compare from image')}</dt><dd>{pair.before.image_revision_id}<br />{pair.before.artifact_hash}</dd></div>
        <div><dt>{t('Compare to image')}</dt><dd>{pair.after.image_revision_id}<br />{pair.after.artifact_hash}</dd></div>
        <div><dt>{t('Comparison hash')}</dt><dd>{query.data.content_hash}</dd></div>
      </dl></details>
      <p>{t('{count} frozen records', { count: query.data.total })}</p>
      {!query.data.items.length && <p>{t('No code members in this comparison category. This does not establish coverage.')}</p>}
      <ul className="image-revision-rows" aria-label={t('Code member changes')}>{query.data.items.map((item) =>
        <li key={`${item.binding_id}:${item.entity_id}`} data-entity-id={item.entity_id}>
          <div className="image-row-heading"><strong>{item.entity_id}</strong><span>{tx(labels[item.kind])}</span></div>
          <details className="image-source-document"><summary>{t('Fixed member references')}</summary><dl>
            <div><dt>{t('Source binding')}</dt><dd>{item.binding_id}</dd></div>
            {([['Before member', item.before], ['After member', item.after]] as const).map(([label, pin]) =>
              <div key={label}><dt>{tx(label)}</dt><dd>{pin ? <>{pin.object_id}<br />{pin.entity_revision_id}<br />{pin.source_revision_id}<br />{pin.object_hash}
                <p>{t('{count} evidence references', { count: pin.evidence_ids.length })}</p></> : t('Not a member of this image')}</dd></div>)}
          </dl></details>
        </li>)}</ul>
      <AnalysisPagination label={t('Code comparison pages')} page={paging.offsets.length}
        previous={paging.offsets.length > 1 ? () => setPaging({ ...paging, offsets: paging.offsets.slice(0, -1) }) : undefined}
        next={query.data.next_offset !== null ? () => setPaging({ ...paging, offsets: [...paging.offsets, query.data.next_offset!] }) : undefined} />
    </div>}
  </section>
}

import { useState } from 'react'
import type { ImageObjectMember } from '../../../../../domains/system-image/types/imageRevision'
import { useImageEvidence, type ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'

export function ImageRevisionEvidence({ scope, revisionId, member }: { scope: ImageReadScope; revisionId: string; member: ImageObjectMember }) {
  const { t } = useI18n()
  const [chosen, setChosen] = useState(member.evidence_ids[0])
  return <section className="image-frozen-evidence">
    <label className="evidence-selector">{t('Frozen evidence reference')}
      <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
        {member.evidence_ids.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
    <FrozenEvidencePage key={chosen} scope={scope} revisionId={revisionId} member={member} evidenceId={chosen} />
  </section>
}

function FrozenEvidencePage({ scope, revisionId, member, evidenceId }: {
  scope: ImageReadScope; revisionId: string; member: ImageObjectMember; evidenceId: string
}) {
  const { t } = useI18n()
  const [starts, setStarts] = useState<(number | undefined)[]>([undefined])
  const query = useImageEvidence(scope, revisionId, member, evidenceId, starts.at(-1))
  if (query.isError) return null
  if (query.isPending || query.isFetching) return <p role="status">{t('Verifying archived source...')}</p>
  const page = query.data
  const lines = page.content.split('\n').slice(0, page.end_line - page.start_line + 1)
  return <>
    <p className="evidence-verified" role="status">{t('Verified against archived file and snippet hashes')}</p>
    <p className="image-evidence-location">{page.evidence.locator.relative_path}:{page.start_line}-{page.end_line}</p>
    <div className="evidence-source-code" tabIndex={0} role="region" aria-label={t('Archived source code')}>
      <pre>{lines.map((line, index) => <span className="evidence-source-line" key={page.start_line + index}>
        <span className="evidence-line-number" aria-hidden="true">{page.start_line + index}</span><code>{line || '\u00a0'}</code>
      </span>)}</pre>
    </div>
    <AnalysisPagination label={t('Evidence pages')} page={starts.length} previous={starts.length > 1 ? () => setStarts(starts.slice(0, -1)) : undefined}
      next={page.next_start_line !== null ? () => setStarts([...starts, page.next_start_line!]) : undefined} />
    <details className="evidence-integrity-details"><summary>{t('Integrity details')}</summary><dl>
      <dt>{t('Pinned source revision')}</dt><dd>{page.evidence.source_revision_id}</dd>
      <dt>{t('File hash')}</dt><dd>{page.evidence.file_hash}</dd>
      <dt>{t('Snippet hash')}</dt><dd>{page.evidence.snippet_hash}</dd>
    </dl></details>
  </>
}

import type { SourceEvidence, SourceEvidencePage } from '../../../../domains/system-image/types'
import { useSourceEvidencePages } from '../../../../domains/system-image/useSourceEvidence'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function EvidenceSourceView({ projectId, evidence }: { projectId: string; evidence: SourceEvidence }) {
  const { t } = useI18n()
  const query = useSourceEvidencePages(projectId, evidence)
  if (evidence.locator.precision !== 'exact') return <p>{t('This location is approximate. No exact excerpt is claimed.')}</p>
  if (query.isError) return <div role="alert">
    <p>{t('Source verification failed or access was revoked. Unverified text is not displayed.')}</p>
    <button onClick={() => void query.refetch()}>{t('Retry')}</button>
  </div>
  if (query.isPending) return <p role="status">{t('Verifying archived source...')}</p>
  return (
    <>
      <p className="evidence-verified" role="status">{t('Verified against archived file and snippet hashes')}</p>
      <div className="evidence-source-code" tabIndex={0} role="region" aria-label={t('Archived source code')}>
        {query.data.pages.map((page) => <SourceLines key={page.start_line} page={page} />)}
      </div>
      {query.hasNextPage && <button type="button" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
        {t(query.isFetchingNextPage ? 'Loading evidence...' : 'Load more lines')}
      </button>}
      <details className="evidence-integrity-details">
        <summary>{t('Integrity details')}</summary>
        <dl><dt>{t('File hash')}</dt><dd>{evidence.file_hash}</dd>
          <dt>{t('Snippet hash')}</dt><dd>{evidence.snippet_hash}</dd>
          <dt>{t('Decoder version')}</dt><dd>{evidence.decoder_version}</dd></dl>
      </details>
    </>
  )
}

function SourceLines({ page }: { page: SourceEvidencePage }) {
  const lines = page.content.split('\n').slice(0, page.end_line - page.start_line + 1)
  return <pre>{lines.map((line, index) => (
    <span className="evidence-source-line" key={page.start_line + index}>
      <span className="evidence-line-number" aria-hidden="true">{page.start_line + index}</span>
      <code>{line || '\u00a0'}</code>
    </span>
  ))}</pre>
}

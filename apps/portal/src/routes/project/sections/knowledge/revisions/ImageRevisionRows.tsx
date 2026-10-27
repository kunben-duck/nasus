import { useState } from 'react'
import type { ImageRowView } from '../../../../../domains/system-image/imageRevisionView'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ImageRevisionEvidence } from './ImageRevisionEvidence'
import { ImageSourceDocument } from './ImageSourceDocument'

export function ImageRevisionRows({ scope, revisionId, imageHash, rows }: { scope: ImageReadScope; revisionId: string; imageHash: string; rows: ImageRowView[] }) {
  const { t, tx } = useI18n()
  const [expanded, setExpanded] = useState('')
  return <ul className="image-revision-rows" aria-label={t('Frozen image records')}>
    {rows.map((row) => <li key={row.id} data-object-id={row.id}>
      <div className="image-row-heading"><strong>{row.title}</strong><span>{tx(row.kind)}{row.objectType && ` · ${tx(row.objectType)}`}</span></div>
      {row.reviewStatus && <p>{tx(row.reviewStatus)}</p>}
      <details className="evidence-integrity-details"><summary>{t('Frozen record details')}</summary>
        <dl>{row.details.filter(([, value]) => value).map(([label, value]) => <div key={label}>
          <dt>{tx(label)}</dt><dd>{value}</dd></div>)}</dl>
      </details>
      {row.member && <div className="image-row-evidence">
        <p>{t('{count} frozen evidence references', { count: row.member.evidence_ids.length })}</p>
        {row.member.evidence_ids.length > 0 ? <button type="button" aria-expanded={expanded === row.id}
          onClick={() => setExpanded(expanded === row.id ? '' : row.id)}>
          {t(expanded === row.id ? 'Hide evidence' : 'Inspect frozen evidence')}</button>
          : <p>{t('No verified evidence is pinned to this object.')}</p>}
        {expanded === row.id && <>
          {row.member.kind === 'source_document' && <ImageSourceDocument scope={scope} revisionId={revisionId} imageHash={imageHash} member={row.member} />}
          <ImageRevisionEvidence scope={scope} revisionId={revisionId} member={row.member} />
        </>}
      </div>}
    </li>)}
  </ul>
}

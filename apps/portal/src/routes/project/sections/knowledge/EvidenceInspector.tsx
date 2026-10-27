import { useEffect, useId, useRef, useState } from 'react'
import { useSourceEvidence } from '../../../../domains/system-image/useSourceEvidence'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import type { SystemImageKnowledgeCardView } from '../../ProjectSectionViewModels'
import { EvidenceSourceView } from './EvidenceSourceView'
import './evidence-inspector.css'

export function EvidenceInspector({ projectId, object, close }: {
  projectId: string; object: SystemImageKnowledgeCardView; close: () => void
}) {
  const { t } = useI18n()
  const titleId = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const revisionId = object.codeReference?.source_revision_id
  const query = useSourceEvidence(projectId, object.codeReference, object.id)
  const evidence = query.data?.find((item) => item.evidence_id === chosen)
    ?? query.data?.find((item) => item.locator.precision === 'exact') ?? query.data?.[0]

  useEffect(() => {
    const element = dialog.current!
    const opener = document.activeElement
    element.showModal()
    return () => {
      element.close()
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])

  return (
    <dialog ref={dialog} className="evidence-inspector" aria-labelledby={titleId} onCancel={close}>
      <header>
        <div><span className="eyebrow">{t('Source evidence')}</span><h2 id={titleId}>{object.name}</h2></div>
        <button type="button" onClick={close}>{t('Close')}</button>
      </header>
      <div className="evidence-inspector-body">
        {!revisionId ? <p>{t('No pinned source evidence. Rebuild this source to establish verifiable references.')}</p> : (
          <>
            <p className="evidence-revision">{t('Pinned source revision')}<code>{revisionId}</code></p>
            {query.isError ? <div role="alert"><p>{t('Evidence could not be loaded. Access or archive availability may have changed.')}</p>
              <button onClick={() => void query.refetch()}>{t('Retry')}</button></div>
              : query.isPending ? <p role="status">{t('Loading evidence...')}</p>
                : !evidence ? <p>{t('No locatable evidence was registered for this object and revision.')}</p> : (
                  <>
                    <label className="evidence-selector">{t('Source location')}
                      <select aria-label={t('Source location')} value={evidence.evidence_id} onChange={(event) => setChosen(event.target.value)}>
                        {query.data.map((item) => <option key={item.evidence_id} value={item.evidence_id}>
                          {item.locator.relative_path}:{item.locator.start_line}-{item.locator.end_line} ({t(item.locator.precision === 'exact' ? 'Exact location' : 'Approximate location')})
                        </option>)}
                      </select>
                    </label>
                    <EvidenceSourceView key={evidence.evidence_id} projectId={projectId} evidence={evidence} />
                  </>
                )}
          </>
        )}
      </div>
    </dialog>
  )
}

import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ImageRevisionSelector } from './ImageRevisionSelector'
import '../evidence-inspector.css'
import '../analysis/analysis-inspector.css'
import './image-revisions.css'
import type { ImageBaselineOption } from '../../../../../domains/system-image/types/baseline'
import type { BuildReviewHandoff } from '../../../../../domains/system-image/buildReviewHandoff'
import { ImageRevisionData } from './ImageRevisionData'
import { BuildCompletionPanel } from './BuildCompletionPanel'

export function ImageRevisionInspector({ projectId, close, baselines, review, reloadReview }: {
  projectId: string; close: () => void; baselines: ImageBaselineOption[]; review?: BuildReviewHandoff; reloadReview?: () => void
}) {
  const { t, tx } = useI18n()
  const titleId = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const [failed, setFailed] = useState(false)
  const [generation, setGeneration] = useState(0)
  useEffect(() => {
    const element = dialog.current!
    const opener = document.activeElement
    element.showModal()
    return () => { element.close(); if (opener instanceof HTMLElement && opener.isConnected) opener.focus() }
  }, [])
  const reload = () => {
    if (review && reloadReview) reloadReview()
    else { setFailed(false); setGeneration((value) => value + 1) }
  }
  return <dialog ref={dialog} className="evidence-inspector image-revision-inspector" aria-labelledby={titleId} onCancel={close}>
    <header><div><span className="eyebrow">{t('System image')}</span><h2 id={titleId}>{t('Image revisions')}</h2></div>
      <button type="button" onClick={close}>{t('Close')}</button></header>
    <div className="evidence-inspector-body">
      <div className="analysis-toolbar"><p className="analysis-scope-note">
        {t('Frozen static candidates, not approved releases. Inferred relationships are not validated business rules.')}
      </p><button type="button" onClick={reload}>{t('Reload revisions')}</button></div>
      {failed ? <p role="alert">{t('Image revision could not be verified. Previous content is hidden; reload to check access.')}</p>
        : review ? <div key={generation} data-testid="saved-build-review">
          <p>{t('These findings belong to the original goal and exact candidate. Reviewing them does not complete the goal, approve business rules or publish knowledge.')}</p>
          <div className="image-source-document"><dl>
            <div><dt>{t('Revision ID')}</dt><dd>{review.image.image_revision_id}</dd></div>
            <div><dt>{t('Artifact hash')}</dt><dd>{review.image.artifact_hash}</dd></div>
          </dl></div>
          <BuildCompletionPanel review={review} />
          <div className="image-revision-status">
            <strong>{t('Remaining investigation gaps')}</strong>
            <ul>{review.investigation.review.gaps.map((gap) => <li key={gap.code}>
              <code>{gap.code}</code><p>{tx(gap.reason)}</p><p>{tx(gap.required_action)}</p>
            </li>)}</ul>
          </div>
          <ImageRevisionData scope={{ projectId, sessionId: `${titleId}:${generation}`, onFailure: setFailed }}
            revisionId={review.image.image_revision_id} baselines={baselines} expectedPin={review.image} />
        </div> : <ImageRevisionSelector key={generation} baselines={baselines} scope={{ projectId, sessionId: `${titleId}:${generation}`, onFailure: setFailed }} />}
    </div>
  </dialog>
}

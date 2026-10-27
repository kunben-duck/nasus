import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { BuildPlanSelector } from './BuildPlanSelector'
import '../evidence-inspector.css'
import '../analysis/analysis-inspector.css'
import '../revisions/image-revisions.css'
import './build-plans.css'
import type { BaselineRecord } from '../../../../../domains/system-image/types/baseline'

export function BuildPlanInspector({ projectId, manifestId, baselines, close }: { projectId: string; manifestId?: string; baselines: BaselineRecord[]; close: () => void }) {
  const { t } = useI18n()
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
  return <dialog ref={dialog} className="evidence-inspector image-revision-inspector" aria-labelledby={titleId} onCancel={close}>
    <header><div><span className="eyebrow">{t('System image')}</span><h2 id={titleId}>{t('Investigation plans')}</h2></div>
      <button type="button" onClick={close}>{t('Close')}</button></header>
    <div className="evidence-inspector-body">
      <div className="analysis-toolbar"><p className="analysis-scope-note">{t('Plans are proposals. Structural tasks require separate confirmation; publication is a separate approval.')}</p>
        <button type="button" onClick={() => { setFailed(false); setGeneration((value) => value + 1) }}>{t('Reload plans')}</button></div>
      {failed ? <p role="alert">{t('Build plan could not be verified. Previous content is hidden; reload to check access.')}</p>
        : <BuildPlanSelector key={generation} manifestId={manifestId} baselines={baselines}
          scope={{ projectId, sessionId: `${titleId}:${generation}`, onFailure: setFailed }} />}
    </div>
  </dialog>
}

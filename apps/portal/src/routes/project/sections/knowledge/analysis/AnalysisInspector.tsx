import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisSourceSelector } from './AnalysisSourceSelector'
import '../evidence-inspector.css'
import './analysis-inspector.css'

export function AnalysisInspector({ projectId, close }: { projectId: string; close: () => void }) {
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
  const reload = () => { setFailed(false); setGeneration((value) => value + 1) }
  return <dialog ref={dialog} className="evidence-inspector analysis-inspector" aria-labelledby={titleId} onCancel={close}>
    <header><div><span className="eyebrow">{t('System image')}</span><h2 id={titleId}>{t('Source analyses')}</h2></div>
      <button type="button" onClick={close}>{t('Close')}</button></header>
    <div className="evidence-inspector-body">
      <div className="analysis-toolbar"><p className="analysis-scope-note">
        {t('Static analysis only. Parsing does not establish business correctness or release readiness.')}<br />
        {t('This captured source is not an approved system image version.')}
      </p><button type="button" onClick={reload}>{t('Reload analyses')}</button></div>
      {failed ? <p role="alert">{t('Source analysis could not be verified. Previous reports are hidden; reload to check access.')}</p>
        : <AnalysisSourceSelector key={generation} scope={{ projectId, sessionId: `${titleId}:${generation}`, onFailure: setFailed }} />}
    </div>
  </dialog>
}

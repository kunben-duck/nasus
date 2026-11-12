import { useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuthUser } from '../../../../domains/platform/useAuthSession'
import { requirementAttemptKey, requirementRevisionsApi, restoreRequirementAttempt, verifyRequirementInput } from '../../../../domains/quality-loop/requirementRevisions'
import type { ClarificationAnswer, RequirementAttempt, RequirementRevision } from '../../../../domains/quality-loop/requirementRevisions'
import type { DeliveryImagePin } from '../../../../domains/quality-loop/types/delivery'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

type Props = { projectId: string; versionId: string; image: DeliveryImagePin }

export function RequirementIntakePanel(props: Props) {
  const actor = useAuthUser()
  if (actor.isError || !actor.data) return null
  return <RequirementIntake key={`${props.projectId}:${props.versionId}:${actor.data.id}`} {...props} actorId={actor.data.id} />
}

function RequirementIntake({ projectId, versionId, image, actorId }: Props & { actorId: string }) {
  const { t } = useI18n(), client = useQueryClient(), session = useId(), busy = useRef(false)
  const storageKey = requirementAttemptKey(actorId, projectId, versionId)
  const [restored] = useState(() => {
    try { return { attempt: restoreRequirementAttempt(sessionStorage.getItem(storageKey), actorId, projectId, versionId), error: false } }
    catch { return { attempt: null, error: true } }
  })
  const [attempt, setAttempt] = useState<RequirementAttempt | null>(restored.attempt)
  const [error, setError] = useState(restored.error ? t('Requirement recovery is unavailable. No write was sent.') : '')
  const [editing, setEditing] = useState<RequirementRevision | null>(null)
  const [title, setTitle] = useState(restored.attempt?.input.title ?? '')
  const [text, setText] = useState(restored.attempt?.input.text ?? '')
  const [answers, setAnswers] = useState<ClarificationAnswer[]>(restored.attempt?.input.clarification_answers ?? [])
  const [offset, setOffset] = useState(0), [historyId, setHistoryId] = useState('')
  const query = useQuery({ queryKey: ['version-requirements', projectId, versionId, actorId, session, offset, historyId],
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => requirementRevisionsApi.list(projectId, versionId, signal, historyId || undefined, offset) })
  const page = !query.isFetching && !query.isError ? query.data : undefined
  const write = useMutation({ mutationFn: requirementRevisionsApi.save, retry: false,
    onSuccess: (result) => {
      if (!['completed', 'failed', 'cancelled'].includes(result.status)) {
        setError(t('The original command has not finished. Retry only this command.')); return
      }
      sessionStorage.removeItem(storageKey); setAttempt(null)
      if (result.status === 'completed') {
        setTitle(''); setText(''); setAnswers([]); setEditing(null)
        setHistoryId(''); setOffset(0)
        setError(''); void client.invalidateQueries({ queryKey: ['version-requirements', projectId, versionId] })
        void client.invalidateQueries({ queryKey: ['project', projectId] })
      } else setError(result.result?.summary ?? result.summary)
    },
    onError: () => setError(t('The save could not be verified. Retry the same command; do not create a replacement.')),
    onSettled: () => { busy.current = false } })

  function save() {
    if (busy.current || !page || restored.error) return
    try {
      const value = attempt ?? { actor_id: actorId, key: crypto.randomUUID(), input: verifyRequirementInput({
        project_id: projectId, version_id: versionId, image_revision_id: image.image_revision_id,
        image_artifact_hash: image.image_artifact_hash, title, text, clarification_answers: answers,
        ...(editing ? { us_id: editing.us_id, expected_revision_id: editing.revision_id } : {}),
      }) }
      sessionStorage.setItem(storageKey, JSON.stringify(value))
      setAttempt(value); busy.current = true; setError(''); write.mutate(value)
    } catch { setError(t('Complete the requirement and each clarification answer before saving.')) }
  }
  function edit(item: RequirementRevision) {
    if (attempt || write.isPending) return
    setEditing(item); setTitle(item.title); setText(item.text); setAnswers(item.clarification_answers); setError('')
  }
  return <section className="delivery-panel" data-testid="requirement-intake" aria-label={t('Iteration requirements')}>
    <div className="delivery-toolbar"><h2>{t('Iteration requirements')}</h2>
      <button type="button" className="small-btn" disabled={query.isFetching} onClick={() => void query.refetch()}>{t('Reload requirements')}</button></div>
    <p className="delivery-notice">{t('Draft intake only. Semantic review, source projection and independent confirmation are still required before formal test generation.')}</p>
    {query.isFetching && <p role="status">{t('Verifying requirement access...')}</p>}
    {query.isError && <p role="alert">{t('Requirements could not be verified. Previous content is hidden.')}</p>}
    {page && <>
      {historyId && <button type="button" className="small-btn" onClick={() => { setHistoryId(''); setOffset(0) }}>{t('Back to current requirements')}</button>}
      {page.items.map((item) => <article className="delivery-pin requirement-draft" key={item.revision_id}>
        <div className="delivery-toolbar"><h3>{item.title}</h3><span>{t('Draft')} · {item.sequence}</span></div>
        <p className="requirement-text">{item.text}</p>
        {item.clarification_answers.map((answer, index) => <dl key={index}>
          <dt>{answer.question}</dt><dd>{answer.answer}</dd></dl>)}
        <div className="delivery-links">
          {!historyId && <button type="button" className="small-btn" disabled={!!attempt || write.isPending} onClick={() => edit(item)}>{t('Revise requirement')}</button>}
          <button type="button" className="small-btn" onClick={() => { setHistoryId(item.us_id); setOffset(0) }}>{t('Revision history')}</button>
        </div>
      </article>)}
      {!page.items.length && <p>{t('No requirement drafts in this iteration yet.')}</p>}
      <div className="delivery-links">
        {offset > 0 && <button type="button" className="small-btn" onClick={() => setOffset(Math.max(0, offset - 20))}>{t('Previous')}</button>}
        {page.next_offset !== null && <button type="button" className="small-btn" onClick={() => setOffset(page.next_offset!)}>{t('Next')}</button>}
      </div>
      <form onSubmit={(event) => { event.preventDefault(); save() }}>
        <fieldset disabled={write.isPending || !!attempt || restored.error}>
          <legend>{t(editing ? 'Revise requirement' : 'Add requirement draft')}</legend>
          <label>{t('Requirement title')}<input value={title} maxLength={200} required onChange={(event) => setTitle(event.target.value)} /></label>
          <label>{t('Requirement description')}<textarea value={text} maxLength={16000} required rows={5} onChange={(event) => setText(event.target.value)} /></label>
          {answers.map((answer, index) => <div className="delivery-pin" key={index}>
            <label>{t('Clarification question')}<input value={answer.question} maxLength={2000} required
              readOnly={index < (editing?.clarification_answers.length ?? 0)} onChange={(event) => setAnswers(answers.map((item, i) => i === index ? { ...item, question: event.target.value } : item))} /></label>
            <label>{t('Your answer')}<textarea value={answer.answer} maxLength={4000} required rows={2}
              onChange={(event) => setAnswers(answers.map((item, i) => i === index ? { ...item, answer: event.target.value } : item))} /></label>
          </div>)}
          <button type="button" className="small-btn" disabled={answers.length >= 32} onClick={() => setAnswers([...answers, { question: '', answer: '' }])}>{t('Add clarification answer')}</button>
        </fieldset>
        <div className="delivery-links">
          <button type="submit" className="small-btn primary" disabled={write.isPending || restored.error}>{t(attempt ? 'Retry original save' : 'Save draft revision')}</button>
          {editing && !attempt && <button type="button" className="small-btn" disabled={write.isPending} onClick={() => { setEditing(null); setTitle(''); setText(''); setAnswers([]) }}>{t('Cancel')}</button>}
        </div>
      </form>
    </>}
    {error && <p role="alert">{error}</p>}
    {write.isPending && <p role="status">{t('Saving requirement revision...')}</p>}
  </section>
}

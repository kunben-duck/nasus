import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { type RequirementRevision } from '../../../../domains/quality-loop/requirementRevisions'
import { requirementReviewsApi, type RequirementReviewPreview } from '../../../../domains/quality-loop/requirementReviews'

export function RequirementReviewPanel({ revision, actorId }: { revision: RequirementRevision; actorId: string }) {
  const { locale } = useI18n(), client = useQueryClient(), zh = locale === 'zh'
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [preview, setPreview] = useState<RequirementReviewPreview | null>(null)
  const processing = useRef(false)
  const [answers, setAnswers] = useState<Record<string, string>>({}), [reason, setReason] = useState('')
  const selection = { project_id: revision.project_id, version_id: revision.version_id, revision_id: revision.revision_id }
  const query = useQuery({ queryKey: ['requirement-review', revision.revision_id, actorId], enabled: open,
    queryFn: ({ signal }) => requirementReviewsApi.read(selection, signal), retry: false, gcTime: 0, staleTime: 0 })
  const view = !query.isError && !query.isFetching ? query.data : undefined
  const assessment = view && !['draft', 'review_pending', 'review_failed', 'image_changed'].includes(view.status)
    ? view.evaluation?.payload.assessment : undefined
  const labels: Record<string, string> = { draft: '待评审', clarification_required: '待澄清', awaiting_confirmation: '待独立确认',
    confirmed: '需求已确认', superseded: '已被新修订替代', approval_invalidated: '批准已失效', review_pending: '评审中或等待恢复', review_failed: '评审失败', image_changed: '画像已更新，请修订需求关联' }
  const fields: Record<string, string> = { roles: '角色与权限', preconditions: '前置条件', inputs_outputs: '输入与输出',
    errors: '异常路径', verifiability: '可验证性', conflicts: '冲突检查', action: '操作', observation: '观察方式', expected_result: '预期结果' }
  async function run(operation: () => Promise<void>) {
    if (processing.current) return
    processing.current = true
    setBusy(true); setError('')
    try { await operation(); await query.refetch(); await client.invalidateQueries({ queryKey: ['version-delivery', revision.project_id, revision.version_id] }) }
    catch (err) { setError(err instanceof Error ? err.message : (zh ? '操作未完成，请检查后重试原命令。' : 'The operation could not be verified.')) }
    finally { processing.current = false; setBusy(false) }
  }
  async function saveAnswers() {
    const updated = new Map(revision.clarification_answers.map((item) => [item.question, item.answer]))
    for (const [question, answer] of Object.entries(answers)) if (answer.trim()) updated.set(question, answer.trim())
    if (!Object.values(answers).some((value) => value.trim())) throw new Error(zh ? '请先填写澄清回答。' : 'Provide a clarification answer first.')
    await requirementReviewsApi.execute(actorId, 'quality.requirement.revise', {
      project_id: revision.project_id, version_id: revision.version_id, us_id: revision.us_id,
      expected_revision_id: revision.revision_id, image_revision_id: revision.image_revision_id,
      image_artifact_hash: revision.image_artifact_hash, title: revision.title, text: revision.text,
      clarification_answers: Array.from(updated, ([question, answer]) => ({ question, answer })),
    })
    await client.invalidateQueries({ queryKey: ['version-requirements', revision.project_id, revision.version_id] })
  }
  async function confirm() {
    const current = await requirementReviewsApi.read(selection)
    if (!current.can_confirm || !current.evaluation || !reason.trim()) throw new Error(zh ? '需要独立审核人、有效评审和确认理由。' : 'An independent reviewer, current review and reason are required.')
    // This explicit human action approves only the displayed, pinned proposal.
    if (current.evaluation.event_id !== view?.evaluation?.event_id) throw new Error(zh ? '评审已更新，请重新查看。' : 'The review changed; reload it.')
    for (const criterion of current.approval_requests) {
      if (criterion.current?.status === 'approved' && criterion.current.authority_actor === actorId) continue
      await requirementReviewsApi.execute(actorId, 'quality.acceptance_specification.review', { ...criterion.input, reason: reason.trim() })
    }
    await requirementReviewsApi.execute(actorId, 'quality.requirement.confirm', { ...selection,
      evaluation_id: current.evaluation.event_id, review_digest: current.evaluation.content_hash, reason: reason.trim() })
  }
  return <div className="requirement-review" data-testid="requirement-review">
    <button type="button" className="small-btn" onClick={() => setOpen(!open)}>{zh ? '需求评审与确认' : 'Review and confirm requirement'}</button>
    {open && <>
      {query.isFetching && <p role="status">{zh ? '正在核对最新评审与权限…' : 'Verifying review and access...'}</p>}
      {query.isError && <p role="alert">{zh ? '评审不可读取，已隐藏历史内容。' : 'Review unavailable. Previous content is hidden.'}</p>}
      {view && <>
        <p><strong>{zh ? labels[view.status] || view.status : view.status.replaceAll('_', ' ')}</strong></p>
        {view.current && view.status !== 'confirmed' && <button type="button" className="small-btn" disabled={busy}
          onClick={() => void run(async () => setPreview(await requirementReviewsApi.preview(selection)))}>{zh ? '准备模型评审' : 'Prepare model review'}</button>}
        {preview && <div className="delivery-pin">
          <p>{zh ? '将向模型发送当前需求、澄清回答和选定证据。模型只提出建议，不会自动批准。' : 'Send the requirement, answers and selected evidence to the model. Suggestions are not approvals.'}</p>
          <p>{preview.model.provider} / {preview.model.model}</p>
          {preview.model.generation_options?.thinking_mode === 'disabled' && <p>{zh
            ? '本次采用结构化评审专用的非思考模式，不修改日常聊天配置。'
            : 'This structured review uses non-thinking mode; ordinary chat settings are unchanged.'}</p>}
          <details><summary>{zh ? '查看本次发送的证据' : 'Inspect selected evidence'}</summary>{preview.evidence.map((item) =>
            <div key={item.ref}><strong>{item.title || item.question || item.kind}</strong><p className="requirement-text">{item.text || item.answer}</p></div>)}</details>
          <button type="button" className="small-btn primary" disabled={busy} onClick={() => void run(async () => {
            await requirementReviewsApi.execute(actorId, 'quality.requirement.evaluate', preview.request); setPreview(null)
          })}>{zh ? '确认发送并开始评审' : 'Confirm and start review'}</button>
        </div>}
        {assessment && <>
          <p className="requirement-text">{assessment.summary}</p>
          <details><summary>{zh ? '评审依据与检查项' : 'Review checks and references'}</summary>
            {assessment.checks.map((check) => <p key={check.dimension}><strong>{zh ? fields[check.dimension] : check.dimension}</strong>: {check.assessment}<br /><small>{check.refs.join(', ')}</small></p>)}</details>
          {assessment.suggestions.length > 0 && <ul>{assessment.suggestions.map((text, index) => <li key={index}>{text}</li>)}</ul>}
          {assessment.questions.map((item) => <label className="review-question" key={item.question}>
            <strong>{item.blocking ? (zh ? '待澄清：' : 'Blocking: ') : ''}{item.question}</strong><p>{item.rationale}</p>
            {view.current && <textarea rows={3} maxLength={4000} value={answers[item.question] ?? ''} disabled={busy}
              onChange={(event) => setAnswers({ ...answers, [item.question]: event.target.value })} />}
          </label>)}
          {view.current && assessment.questions.length > 0 && <button type="button" className="small-btn" disabled={busy}
            onClick={() => void run(saveAnswers)}>{zh ? '保存回答为新修订' : 'Save answers as a new revision'}</button>}
          {assessment.criteria.map((item, index) => <div className="delivery-pin" key={index}><strong>{index + 1}. {item.title}</strong>
            <dl>{Object.entries(item.oracle).map(([key, value]) => <div key={key}><dt>{zh ? fields[key] || key : key}</dt><dd>{value}</dd></div>)}</dl></div>)}
        </>}
        {['awaiting_confirmation', 'approval_invalidated'].includes(view.status) && <>
          <p>{zh ? '请由非需求编写者、非评审发起者的项目管理员核对并批准下列条件。这不代表测试通过或版本放行。' : 'A different project administrator must approve these criteria. This does not pass tests or release the iteration.'}</p>
          {view.can_confirm && <><label>{zh ? '确认理由' : 'Confirmation reason'}<textarea rows={2} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <button type="button" className="small-btn primary" disabled={busy || !reason.trim()} onClick={() => void run(confirm)}>
              {zh ? '批准以上验收条件并确认需求' : 'Approve these criteria and confirm requirement'}</button></>}
        </>}
      </>}
      {busy && <p role="status">{zh ? '正在处理，请勿重复提交…' : 'Processing the original command...'}</p>}
      {error && <p role="alert">{error}</p>}
      <button type="button" className="small-btn" disabled={busy || query.isFetching} onClick={() => void query.refetch()}>{zh ? '刷新评审状态' : 'Reload review'}</button>
    </>}
  </div>
}

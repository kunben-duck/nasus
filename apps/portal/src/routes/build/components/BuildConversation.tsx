import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ConversationSession } from '../../../domains/agent/types'
import { uploadSystemImageSourceFiles } from '../../../domains/system-image/sourceUploadCommands'
import { buildReviewHref } from '../../../domains/system-image/buildReviewHandoff'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../shared/ui/MarkdownContent'
import { useBuildHistoryScroll } from '../useBuildHistoryScroll'
import { BuildImageStatus } from './BuildImageStatus'
import { BuildDeliveryCard } from './BuildDeliveryCard'

export function BuildConversation({ conversation, sendPrompt, busy }: {
  conversation?: ConversationSession
  sendPrompt: (content: string) => Promise<void>
  busy: boolean
}) {
  const { t, tx, locale } = useI18n()
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const history = useBuildHistoryScroll(Boolean(conversation?.messages.length))
  if (!conversation?.messages.length) return null
  const observedIntake = conversation.messages.findLast((item) => item.role === 'assistant' && item.metadata?.system_image_intake)
    ?.metadata?.system_image_intake as { stage: string; project_id?: string; goal_id?: string; project_name: string; capture_started?: boolean } | undefined
  const intake = observedIntake?.project_id && observedIntake.project_id !== conversation.project_id ? undefined : observedIntake
  const imageGoals = conversation.agent_goals.filter((item) => item.goal_template === 'system_image_build'
    && item.project_id === conversation.project_id)
  const goal = intake?.goal_id ? imageGoals.find((item) => item.id === intake.goal_id)
    : imageGoals.find((item) => !['completed', 'failed', 'cancelled'].includes(item.status)) ?? imageGoals.at(-1)
  const blocked = goal?.steps.findLast((step) => step.phase === 'acting' && step.status === 'blocked')
  const invocation = conversation.tool_invocations.find((item) => item.id === blocked?.tool_invocation_id)
  const reviewHref = goal && buildReviewHref(goal)
  const rawBudget = invocation?.input_payload.budget
  const budget = rawBudget && typeof rawBudget === 'object' && !Array.isArray(rawBudget) ? rawBudget as Record<string, unknown> : undefined
  const messages = conversation.messages.filter((item) => (
    (item.role === 'user' || item.role === 'assistant') && item.content_type !== 'thinking'
  ))
  const canContinue = goal?.status === 'paused' && ['waiting_confirmation', 'structural_candidate_review', 'reference_candidate_review'].includes(goal.pause_reason ?? '')
  const zh = locale === 'zh'

  async function upload(kind: 'us_doc' | 'test_asset', files: File[]) {
    if (!intake?.project_id || !files.length || busy || uploading) return
    setUploading(true)
    setError(null)
    try {
      const result = await uploadSystemImageSourceFiles(intake.project_id, kind, files)
      await sendPrompt(`${kind === 'us_doc' ? '需求文档地址' : '测试资产地址'} ${result.source_uri}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Upload failed'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="build-conversation" data-testid="build-conversation">
      <div className="build-message-list" role="log" aria-label={t('Build conversation')} ref={history.logRef}
        onScroll={history.onScroll}>
        <div className="build-message-content" ref={history.contentRef}>
        {messages.map((message) => (
          <article className={`build-message ${message.role}`} key={message.id}>
            <strong>{message.role === 'user' ? t('You') : 'Nasus'}</strong>
            <MarkdownContent content={message.role === 'user' ? message.blocks.map((block) => block.text).filter(Boolean).join('\n')
              : tx(message.blocks.map((block) => block.text).filter(Boolean).join('\n'))}
              streaming={message.status === 'streaming'} />
          </article>
        ))}
        </div>
      </div>
      {intake?.project_id ? (
        <div className="build-project-context">
          <span>{intake.project_name}</span>
          <Link to={`/projects/${encodeURIComponent(intake.project_id)}/knowledge`}>{t('View system image')}</Link>
        </div>
      ) : null}
      {intake?.stage === 'sources' || intake?.stage === 'review' ? (
        <div className="build-intake-actions">
          {intake.project_id && !intake.capture_started ? (['us_doc', 'test_asset'] as const).map((kind) => (
            <label className="build-upload-button" key={kind}>
              {t(kind === 'us_doc' ? 'Upload requirements' : 'Upload test assets')}
              <input type="file" multiple disabled={busy || uploading} data-testid={`build-upload-${kind}`}
                accept={kind === 'us_doc' ? '.md,.txt,.pdf,.docx' : '.csv,.json,.md,.txt,.py,.js,.ts,.yaml,.yml'}
                onChange={(event) => { void upload(kind, Array.from(event.target.files ?? [])); event.target.value = '' }} />
            </label>
          )) : null}
          {!intake.capture_started ? <button type="button" disabled={busy || uploading} onClick={() => void sendPrompt(zh ? '跳过可选资料' : 'skip optional sources')}>
            {t('Continue with available sources')}
          </button> : null}
          {intake.stage === 'review' ? <button type="button" className="build-confirm" data-testid="build-intake-confirm"
            disabled={busy || uploading} onClick={() => void sendPrompt(zh ? '确认接入并构建' : 'confirm and build')}>
            {t('Confirm sources and build')}
          </button> : null}
        </div>
      ) : null}
      {goal ? <section className="build-progress" data-testid="build-progress" aria-label={t('Build progress')}>
        <div className="build-project-context"><strong>{t('Build progress')}</strong><span>{tx(goal.status)}</span></div>
        <p>{tx(goal.summary)}</p>
        {goal.pause_reason === 'structural_candidate_review' || goal.pause_reason === 'build_completion_review' ?
          <p>{t('Candidate image available. Official publication still requires review.')}</p> : null}
        {reviewHref ? <Link to={reviewHref}>{t('Review saved findings')}</Link> : null}
        {canContinue ? <div className="build-confirmation">
          <p>{invocation ? tx(invocation.summary) : t('Continue inspecting the saved candidate and its evidence.')}</p>
          {budget ? <p data-testid="image-build-execution-budget">
            {t('Structural builds')}: {String(budget.max_tool_calls ?? '-')} · {t('Model calls')}: {String(budget.max_model_calls ?? '-')} ·{' '}
            {t('Active time limit (seconds)')}: {String(budget.max_active_seconds ?? '-')} ·{' '}
            {t('Model cost limit (micro-USD)')}: {String(budget.max_cost_microusd ?? '-')}
          </p> : null}
          {invocation ? <details><summary>{t('Operation details')}</summary><pre>{JSON.stringify(invocation.input_payload, null, 2)}</pre></details> : null}
          <button type="button" disabled={busy} data-testid="build-goal-continue"
            onClick={() => void sendPrompt(zh ? '继续分析' : 'continue analysis')}>
            {t(goal.pause_reason === 'waiting_confirmation' ? 'Confirm and continue' : 'Continue analysis')}
          </button>
        </div> : null}
        <details><summary>{t('Execution history')}</summary>
          <ol>{conversation.tool_invocations.map((item) => <li key={item.id}>
            <span>{item.tool_id}</span> · {tx(item.status)}<p>{tx(item.summary)}</p>
          </li>)}</ol>
        </details>
      </section> : null}
      {!goal && (intake?.stage === 'existing' || conversation.agent_goals.length > 0) ?
        <BuildImageStatus conversation={conversation} sendPrompt={sendPrompt} busy={busy} /> : null}
      <BuildDeliveryCard key={`${conversation.id}:${conversation.project_id}`} conversation={conversation}
        reviewHref={reviewHref} sendPrompt={sendPrompt} busy={busy} />
      {uploading ? <p role="status">{t('Uploading sources...')}</p> : null}
      {error ? <p role="alert">{tx(error)}</p> : null}
    </div>
  )
}

import type { ConversationSession } from '../../../domains/agent/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../shared/ui/MarkdownContent'

interface ImageStatusObservation { project_id: string; status: string; summary: string; next_action: string }

export function BuildImageStatus({ conversation, sendPrompt, busy }: {
  conversation: ConversationSession
  sendPrompt: (content: string) => Promise<void>
  busy: boolean
}) {
  const { t, locale } = useI18n()
  const message = conversation.messages.findLast((item) => item.role === 'assistant' && item.metadata?.system_image_status)
  const observed = message?.metadata?.system_image_status as ImageStatusObservation | undefined
  const status = observed?.project_id === conversation.project_id ? observed : undefined
  const zh = locale === 'zh'
  return <section className="build-progress" data-testid="build-image-status" aria-label={t('System image status')}>
    <strong>{t('System image status')}</strong>
    {status ? <MarkdownContent content={status.summary} />
      : <p>{t('Completed project setup does not mean the system image is built. Check its actual state to continue.')}</p>}
    <div className="build-intake-actions">
      <button type="button" disabled={busy} onClick={() => void sendPrompt(zh ? '系统画像是不是已经构建完成了' : 'Is the system image ready?')}>
        {t('Check image status')}
      </button>
      {status?.next_action === 'build_candidate' ? <button type="button" disabled={busy}
        onClick={() => void sendPrompt(zh ? '继续构建' : 'continue build')}>{t('Continue build')}</button> : null}
      {status?.next_action === 'capture_sources' ? <button type="button" disabled={busy}
        onClick={() => void sendPrompt(zh ? '确认采集已有资料' : 'confirm source capture')}>{t('Capture existing sources')}</button> : null}
    </div>
  </section>
}

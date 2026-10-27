import { lazy, Suspense } from 'react'

import { useI18n } from '../i18n/I18nProvider'
import { useSmoothStreamingText } from './useSmoothStreamingText'

const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

export function MarkdownContent({
  content,
  className = '',
  streaming = false,
}: {
  content: string
  className?: string
  streaming?: boolean
}) {
  const { tx } = useI18n()
  const translatedContent = tx(content)
  const { visibleText, animating } = useSmoothStreamingText(translatedContent, streaming)
  const resolvedClassName = [
    'markdown-content',
    className,
    streaming || animating ? 'is-streaming' : '',
  ].filter(Boolean).join(' ')

  return (
    <div className={resolvedClassName}>
      <Suspense fallback={<p>{visibleText}</p>}>
        <MarkdownRenderer content={visibleText} />
      </Suspense>
    </div>
  )
}

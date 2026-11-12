import { useEffect, useRef } from 'react'

export function useBuildHistoryScroll(hasMessages: boolean) {
  const logRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const previousTop = useRef(0)

  useEffect(() => {
    const log = logRef.current, content = contentRef.current
    if (!log || !content) return
    // Markdown loads and grows after the message snapshot has arrived.
    const resize = new ResizeObserver(() => {
      if (following.current) log.scrollTop = log.scrollHeight
    })
    resize.observe(content)
    resize.observe(log)
    return () => resize.disconnect()
  }, [hasMessages])

  function onScroll() {
    const log = logRef.current
    if (!log) return
    if (log.scrollHeight - log.scrollTop - log.clientHeight < 80) following.current = true
    else if (log.scrollTop < previousTop.current) following.current = false
    previousTop.current = log.scrollTop
  }

  return { logRef, contentRef, onScroll }
}

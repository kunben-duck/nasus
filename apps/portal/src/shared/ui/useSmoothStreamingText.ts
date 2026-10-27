import { useEffect, useRef, useState } from 'react'

const FRAME_INTERVAL_MS = 24

function charactersPerFrame(remaining: number) {
  if (remaining > 180) return Math.min(12, Math.ceil(remaining / 24))
  if (remaining > 80) return 4
  if (remaining > 32) return 2
  return 1
}

export function useSmoothStreamingText(content: string, streaming: boolean) {
  const [visibleText, setVisibleText] = useState(streaming ? '' : content)
  const [animating, setAnimating] = useState(streaming && content.length > 0)
  const targetCharactersRef = useRef(Array.from(content))
  const visibleCharactersRef = useRef(Array.from(streaming ? '' : content))
  const streamingRef = useRef(streaming)
  const shouldAnimateRef = useRef(streaming)
  const frameRef = useRef<number | null>(null)
  const lastFrameAtRef = useRef(0)
  const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

  useEffect(() => {
    streamingRef.current = streaming
    targetCharactersRef.current = Array.from(content)

    const currentText = visibleCharactersRef.current.join('')
    if (!content.startsWith(currentText)) {
      visibleCharactersRef.current = streaming ? [] : targetCharactersRef.current
    }

    if (streaming) shouldAnimateRef.current = true
    if (reducedMotion || (!streaming && !shouldAnimateRef.current)) {
      visibleCharactersRef.current = targetCharactersRef.current
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null
        setVisibleText(content)
        setAnimating(false)
      })
      return () => {
        if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
        frameRef.current = null
      }
    }

    const renderFrame = (timestamp: number) => {
      if (timestamp - lastFrameAtRef.current < FRAME_INTERVAL_MS) {
        frameRef.current = requestAnimationFrame(renderFrame)
        return
      }
      lastFrameAtRef.current = timestamp

      const target = targetCharactersRef.current
      const visibleCount = visibleCharactersRef.current.length
      const remaining = target.length - visibleCount
      if (remaining <= 0) {
        frameRef.current = null
        if (!streamingRef.current) shouldAnimateRef.current = false
        setAnimating(false)
        return
      }

      const nextCount = Math.min(target.length, visibleCount + charactersPerFrame(remaining))
      visibleCharactersRef.current = target.slice(0, nextCount)
      setVisibleText(visibleCharactersRef.current.join(''))
      setAnimating(true)
      frameRef.current = requestAnimationFrame(renderFrame)
    }

    if (frameRef.current === null) {
      frameRef.current = requestAnimationFrame(renderFrame)
    }

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [content, reducedMotion, streaming])

  return { visibleText, animating }
}

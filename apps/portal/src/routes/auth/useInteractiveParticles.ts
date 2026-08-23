import type { PointerEvent } from 'react'
import { useCallback, useRef } from 'react'

type ParticleElement = HTMLElement & {
  dataset: DOMStringMap & {
    active?: string
    x?: string
    y?: string
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function useInteractiveParticles() {
  const lastPoint = useRef<{ x: number; y: number; time: number } | null>(null)
  const idleTimer = useRef<number | null>(null)
  const pendingFrame = useRef<number | null>(null)
  const pendingValues = useRef<{
    host: HTMLElement
    clientX: number
    clientY: number
    vx: number
    vy: number
  } | null>(null)
  const activeParticles = useRef<Set<ParticleElement>>(new Set())
  const particleCache = useRef<ParticleElement[] | null>(null)

  const resetActiveParticles = useCallback((host?: HTMLElement) => {
    host?.style.setProperty('--cursor-glow-opacity', '0')
    activeParticles.current.forEach((particle) => {
      particle.style.setProperty('--local-x', '0px')
      particle.style.setProperty('--local-y', '0px')
      particle.style.setProperty('--local-glow', '0')
      delete particle.dataset.active
    })
    activeParticles.current.clear()
  }, [])

  const flush = useCallback(() => {
    const values = pendingValues.current
    pendingFrame.current = null
    if (!values) return

    values.host.style.setProperty('--cursor-screen-x', `${values.clientX}px`)
    values.host.style.setProperty('--cursor-screen-y', `${values.clientY}px`)
    values.host.style.setProperty('--cursor-glow-opacity', '1')

    const field = values.host.querySelector('.ai-interactive-particles')
    if (!field) return

    if (!particleCache.current) {
      particleCache.current = Array.from(field.querySelectorAll<ParticleElement>('span'))
    }

    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const radius = 165
    const radiusSquared = radius * radius
    const nextActive = new Set<ParticleElement>()

    particleCache.current.forEach((particle) => {
      const particleX = Number(particle.dataset.x ?? 0) * viewportWidth
      const particleY = Number(particle.dataset.y ?? 0) * viewportHeight
      const deltaX = values.clientX - particleX
      const deltaY = values.clientY - particleY
      const distanceSquared = deltaX * deltaX + deltaY * deltaY

      if (distanceSquared > radiusSquared) return

      const distance = Math.sqrt(distanceSquared)
      const influence = (1 - distance / radius) ** 2
      const directionX = values.vx * influence * 1.28
      const directionY = values.vy * influence * 1.28
      const gravityX = (deltaX / Math.max(distance, 1)) * influence * 5
      const gravityY = (deltaY / Math.max(distance, 1)) * influence * 5
      const localX = clamp(directionX + gravityX, -20, 20)
      const localY = clamp(directionY + gravityY, -20, 20)

      particle.style.setProperty('--local-x', `${localX}px`)
      particle.style.setProperty('--local-y', `${localY}px`)
      particle.style.setProperty('--local-glow', `${0.2 + influence * 0.95}`)
      particle.dataset.active = 'true'
      nextActive.add(particle)
    })

    activeParticles.current.forEach((particle) => {
      if (nextActive.has(particle)) return
      particle.style.setProperty('--local-x', '0px')
      particle.style.setProperty('--local-y', '0px')
      particle.style.setProperty('--local-glow', '0')
      delete particle.dataset.active
    })

    activeParticles.current = nextActive
  }, [])

  const onPointerMove = useCallback((event: PointerEvent<HTMLElement>) => {
    const host = event.currentTarget
    const now = performance.now()
    const last = lastPoint.current
    let velocityX = 0
    let velocityY = 0

    if (last) {
      const deltaTime = Math.max(16, now - last.time)
      velocityX = clamp(((event.clientX - last.x) / deltaTime) * 520, -38, 38)
      velocityY = clamp(((event.clientY - last.y) / deltaTime) * 520, -38, 38)
    }

    lastPoint.current = { x: event.clientX, y: event.clientY, time: now }
    pendingValues.current = {
      host,
      clientX: event.clientX,
      clientY: event.clientY,
      vx: velocityX,
      vy: velocityY,
    }

    if (pendingFrame.current === null) {
      pendingFrame.current = requestAnimationFrame(flush)
    }

    if (idleTimer.current !== null) {
      window.clearTimeout(idleTimer.current)
    }
    idleTimer.current = window.setTimeout(() => {
      lastPoint.current = null
      resetActiveParticles(host)
    }, 420)
  }, [flush, resetActiveParticles])

  const onPointerLeave = useCallback((event: PointerEvent<HTMLElement>) => {
    lastPoint.current = null
    if (idleTimer.current !== null) {
      window.clearTimeout(idleTimer.current)
      idleTimer.current = null
    }
    const host = event.currentTarget
    resetActiveParticles(host)
  }, [resetActiveParticles])

  return { onPointerLeave, onPointerMove }
}

import type { CSSProperties } from 'react'

function seededUnit(index: number, salt: number) {
  const value = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453123
  return value - Math.floor(value)
}

export function AuthParticleField({
  className = '',
  count = 150,
}: {
  className?: string
  count?: number
}) {
  return (
    <div className={`auth-particles ai-interactive-particles ${className}`.trim()} aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => {
        const x = seededUnit(index + 1, 3)
        const y = seededUnit(index + 1, 17)
        const depth = 0.16 + seededUnit(index + 1, 29) * 0.82
        const bright = seededUnit(index + 1, 43)
        const size = bright > 0.94 ? 3.6 : bright > 0.82 ? 2.6 : 0.9 + seededUnit(index + 1, 59) * 1.35
        const duration = 6.5 + seededUnit(index + 1, 71) * 10.5
        const delay = -seededUnit(index + 1, 89) * duration
        const driftX = (seededUnit(index + 1, 101) - 0.5) * 34
        const driftY = (seededUnit(index + 1, 113) - 0.5) * 28
        const driftDuration = 14 + seededUnit(index + 1, 127) * 20
        const driftDelay = -seededUnit(index + 1, 139) * driftDuration

        return (
          <span
            data-x={x}
            data-y={y}
            key={index}
            style={{
              '--i': index,
              '--depth': `${depth}`,
              '--size': `${size}px`,
              '--duration': `${duration}s`,
              '--twinkle-delay': `${delay}s`,
              '--drift-x': `${driftX}px`,
              '--drift-y': `${driftY}px`,
              '--drift-duration': `${driftDuration}s`,
              '--drift-delay': `${driftDelay}s`,
              left: `${x * 100}%`,
              top: `${y * 100}%`,
            } as CSSProperties & Record<string, number | string>}
          >
            <i />
          </span>
        )
      })}
    </div>
  )
}

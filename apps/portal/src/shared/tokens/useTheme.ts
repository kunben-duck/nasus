import { useEffect } from 'react'

export type ThemePreference = 'dark' | 'light' | 'system'

export function useTheme(theme: ThemePreference = 'dark') {
  useEffect(() => {
    const root = document.documentElement
    const media = window.matchMedia('(prefers-color-scheme: light)')

    function applyTheme() {
      root.dataset.theme = theme === 'system'
        ? (media.matches ? 'light' : 'dark')
        : theme
    }

    applyTheme()
    if (theme !== 'system') return

    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [theme])
}

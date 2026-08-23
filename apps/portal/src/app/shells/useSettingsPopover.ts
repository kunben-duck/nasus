import { useEffect, useState } from 'react'

export function useSettingsPopover() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  useEffect(() => {
    if (!settingsOpen) return

    function closeSettingsOnOutsidePointer(event: PointerEvent) {
      const target = event.target as Element | null
      if (!target) return
      if (target.closest('.settings-pop') || target.closest('[data-settings-toggle]')) return
      setSettingsOpen(false)
    }

    document.addEventListener('pointerdown', closeSettingsOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeSettingsOnOutsidePointer)
  }, [settingsOpen])

  return {
    settingsOpen,
    setSettingsOpen,
    closeSettings: () => setSettingsOpen(false),
  }
}

import { useEffect, useState } from 'react'

import { platformApi } from './api'
import { platformApiAuthToken } from './authTokenStorage'
import { useAuthActions } from './useAuthSession'
import type { UserProfile } from './types'

const MAX_AVATAR_FILE_BYTES = 512 * 1024

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve(String(reader.result || '')))
    reader.addEventListener('error', () => reject(new Error('Unable to read avatar image.')))
    reader.readAsDataURL(file)
  })
}

export function useUserAvatarImage(user?: UserProfile | null): string {
  const legacyAvatarUrl = user?.avatar_url?.trim()
  const avatarImageKey = user?.avatar_image ? `${user.id}:${user.avatar_updated_at || ''}` : ''
  const [objectAvatar, setObjectAvatar] = useState<{ key: string; url: string } | null>(null)

  useEffect(() => {
    if (user?.avatar_preset || legacyAvatarUrl || !user?.avatar_image) {
      return undefined
    }

    const controller = new AbortController()
    let objectUrl = ''

    async function loadAvatar() {
      const token = platformApiAuthToken()
      const response = await fetch(`/v1/auth/me/avatar/content?version=${encodeURIComponent(user?.avatar_updated_at || '')}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal,
      })
      if (!response.ok) return
      const blob = await response.blob()
      objectUrl = URL.createObjectURL(blob)
      setObjectAvatar({ key: avatarImageKey, url: objectUrl })
    }

    void loadAvatar().catch(() => undefined)

    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [avatarImageKey, legacyAvatarUrl, user?.avatar_image, user?.avatar_preset, user?.avatar_updated_at])

  if (!user?.avatar_image) return ''
  return objectAvatar?.key === avatarImageKey ? objectAvatar.url : ''
}

export function useAvatarEditorModel({ variant = 'settings' }: { variant?: 'settings' | 'account' }) {
  const { setUser } = useAuthActions()
  const [status, setStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(variant === 'settings')
  const compact = variant === 'account'

  async function uploadAvatar(file: File) {
    setStatus('')

    if (!file.type.match(/^image\/(png|jpeg|webp|gif)$/)) {
      setStatus('Use a PNG, JPEG, WebP, or GIF image.')
      return
    }

    if (file.size > MAX_AVATAR_FILE_BYTES) {
      setStatus('Avatar must be 512KB or smaller.')
      return
    }

    setSaving(true)
    try {
      const avatarUrl = await readFileAsDataUrl(file)
      const nextUser = await platformApi.updateAvatar({ avatar_url: avatarUrl, avatar_preset: null })
      setUser(nextUser)
      setStatus('Avatar updated.')
      if (compact) setPickerOpen(false)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to update avatar.')
    } finally {
      setSaving(false)
    }
  }

  async function selectPreset(presetId: string) {
    setStatus('')
    setSaving(true)
    try {
      const nextUser = await platformApi.updateAvatar({ avatar_url: null, avatar_preset: presetId })
      setUser(nextUser)
      setStatus('Avatar updated.')
      if (compact) setPickerOpen(false)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to update avatar.')
    } finally {
      setSaving(false)
    }
  }

  return {
    pickerOpen,
    saving,
    status,
    setPickerOpen,
    uploadAvatar,
    selectPreset,
  }
}

export function usePlatformAccountSessionActions() {
  const { clearSession } = useAuthActions()

  return {
    async signOut() {
      await platformApi.logout().catch(() => null)
      clearSession()
    },
    switchAccount() {
      clearSession()
    },
  }
}

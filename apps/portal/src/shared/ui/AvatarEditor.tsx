import { useRef, useState } from 'react'

import { avatarPresets } from './avatarPresets'
import { UserAvatar } from './UserAvatar'
import type { UserAvatarView } from './UserAvatar'

export function AvatarEditor({
  avatarImageUrl = '',
  onPickerOpenChange,
  onSelectPreset,
  onUploadAvatar,
  pickerOpen: controlledPickerOpen,
  saving = false,
  status = '',
  user,
  variant = 'settings',
}: {
  avatarImageUrl?: string
  onPickerOpenChange?: (open: boolean) => void
  onSelectPreset: (presetId: string) => Promise<void> | void
  onUploadAvatar: (file: File) => Promise<void> | void
  pickerOpen?: boolean
  saving?: boolean
  status?: string
  user?: UserAvatarView | null
  variant?: 'settings' | 'account'
}) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [localPickerOpen, setLocalPickerOpen] = useState(variant === 'settings')
  const pickerOpen = controlledPickerOpen ?? localPickerOpen
  const compact = variant === 'account'

  function setPickerOpen(nextOpen: boolean) {
    setLocalPickerOpen(nextOpen)
    onPickerOpenChange?.(nextOpen)
  }

  return (
    <div className={`avatar-editor avatar-editor-${variant}`}>
      <button
        aria-expanded={pickerOpen}
        aria-label={compact ? 'Edit account avatar' : 'Upload account avatar'}
        className={compact ? 'account-avatar-edit-button' : 'settings-avatar-button'}
        disabled={saving}
        onClick={() => {
          if (compact) {
            setPickerOpen(!pickerOpen)
          } else {
            inputRef.current?.click()
          }
        }}
        type="button"
      >
        <UserAvatar user={user} imageUrl={avatarImageUrl} className={compact ? '' : 'large'} />
        {!compact ? <span>{saving ? 'Uploading...' : 'Click to upload avatar'}</span> : null}
      </button>
      <input
        ref={inputRef}
        accept="image/png,image/jpeg,image/webp,image/gif"
        hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0]
          if (file) void Promise.resolve(onUploadAvatar(file)).finally(() => {
            if (inputRef.current) inputRef.current.value = ''
          })
        }}
        type="file"
      />
      {pickerOpen ? (
        <div className={compact ? 'account-avatar-picker' : 'settings-avatar-library'}>
          <button
            className="avatar-upload-action"
            disabled={saving}
            onClick={() => inputRef.current?.click()}
            type="button"
          >
            Upload image
          </button>
          <div className="avatar-preset-grid" aria-label="Default avatar library">
            {avatarPresets.map((preset) => (
              <button
                aria-label={`Use ${preset.label} avatar`}
                className={user?.avatar_preset === preset.id ? 'selected' : ''}
                disabled={saving}
                key={preset.id}
                onClick={() => void onSelectPreset(preset.id)}
                style={{ background: preset.background }}
                title={preset.label}
                type="button"
              >
                <span aria-hidden="true">{preset.glyph}</span>
              </button>
            ))}
          </div>
          {status ? <span className="settings-avatar-status">{status}</span> : null}
        </div>
      ) : null}
      {!pickerOpen && status && !compact ? <span className="settings-avatar-status">{status}</span> : null}
    </div>
  )
}

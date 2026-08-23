import { findAvatarPreset } from './avatarPresets'

export type UserAvatarView = {
  name?: string | null
  email?: string | null
  avatar_preset?: string | null
  avatar_url?: string | null
}

function userInitial(user?: Pick<UserAvatarView, 'name' | 'email'> | null): string {
  return (user?.name || user?.email || 'U').trim().charAt(0).toUpperCase()
}

export function UserAvatar({
  user,
  imageUrl = '',
  className = '',
}: {
  user?: UserAvatarView | null
  imageUrl?: string
  className?: string
}) {
  const preset = findAvatarPreset(user?.avatar_preset)
  const legacyAvatarUrl = user?.avatar_url?.trim()
  const avatarUrl = legacyAvatarUrl || imageUrl

  return (
    <span
      className={`avatar ${avatarUrl ? 'with-image' : ''} ${preset ? 'with-preset' : ''} ${className}`.trim()}
      style={preset ? { background: preset.background } : undefined}
      title={preset?.label}
    >
      {avatarUrl ? <img src={avatarUrl} alt={`${user?.name || 'User'} avatar`} /> : null}
      {!avatarUrl && preset ? <span className="avatar-preset-glyph" aria-hidden="true">{preset.glyph}</span> : null}
      {!avatarUrl && !preset ? userInitial(user) : null}
    </span>
  )
}

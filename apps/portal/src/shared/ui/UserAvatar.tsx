import { findAvatarPreset } from './avatarPresets'
import { useI18n } from '../i18n/I18nProvider'

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
  const { t, tx } = useI18n()
  const preset = findAvatarPreset(user?.avatar_preset)
  const legacyAvatarUrl = user?.avatar_url?.trim()
  const avatarUrl = legacyAvatarUrl || imageUrl

  return (
    <span
      className={`avatar ${avatarUrl ? 'with-image' : ''} ${preset ? 'with-preset' : ''} ${className}`.trim()}
      style={preset ? { background: preset.background } : undefined}
      title={preset ? tx(preset.label) : undefined}
    >
      {avatarUrl ? <img src={avatarUrl} alt={user?.name ? `${user.name} · ${t('User avatar')}` : t('User avatar')} /> : null}
      {!avatarUrl && preset ? <span className="avatar-preset-glyph" aria-hidden="true">{preset.glyph}</span> : null}
      {!avatarUrl && !preset ? userInitial(user) : null}
    </span>
  )
}

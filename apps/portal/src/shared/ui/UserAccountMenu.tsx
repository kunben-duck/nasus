import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { UserAvatar } from './UserAvatar'
import type { UserAvatarView } from './UserAvatar'

export type UserAccountMenuView = UserAvatarView & {
  role?: string | null
}

const ROLE_LABELS: Record<string, string> = {
  platform_admin: 'System administrator',
  project_admin: 'Project administrator',
  qa_lead: 'QA lead',
  tester: 'Tester',
  viewer: 'Viewer',
}

function roleLabel(role?: string | null) {
  return role ? ROLE_LABELS[role] || role : 'Signed-in user'
}

export function UserAccountMenu({
  avatarEditor,
  avatarImageUrl = '',
  onSignOut,
  onSwitchAccount,
  user,
}: {
  avatarEditor: ReactNode
  avatarImageUrl?: string
  onSignOut: () => Promise<void> | void
  onSwitchAccount: () => void
  user?: UserAccountMenuView | null
}) {
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (accountRef.current && !accountRef.current.contains(event.target as Node)) {
        setAccountOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [])

  return (
    <div className="account-menu-wrap" ref={accountRef}>
      {accountOpen ? (
        <div className="account-menu" role="menu">
          <div className="account-menu-profile">
            {avatarEditor}
            <div>
              <strong>{user?.name || 'Nasus User'}</strong>
              <span>{user?.email || 'Signed in'}</span>
            </div>
          </div>
          <div className="account-role-row">
            <span>Role</span>
            <strong>{roleLabel(user?.role)}</strong>
          </div>
          <button className="account-menu-item" type="button" onClick={onSwitchAccount}>Switch account</button>
          <button className="account-menu-item danger" type="button" onClick={() => void onSignOut()}>Sign out</button>
        </div>
      ) : null}
      <button className="account-pill" type="button" aria-haspopup="menu" aria-expanded={accountOpen} onClick={() => setAccountOpen((value) => !value)}>
        <UserAvatar user={user} imageUrl={avatarImageUrl} />
        <span>{user?.email || 'Account'}</span>
      </button>
    </div>
  )
}

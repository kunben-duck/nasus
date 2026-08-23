import type { ReactNode } from 'react'

import type { ReturnTypeOfIdentityAdministration } from './identityAdministrationTypes'
import type { AccountStatus, GlobalRole, UserProfile } from '../../../domains/platform/types'


const globalRoles: GlobalRole[] = ['viewer', 'tester', 'qa_lead', 'platform_admin']
const roleLabels: Record<GlobalRole, string> = {
  viewer: 'Viewer',
  tester: 'Tester',
  qa_lead: 'QA lead',
  platform_admin: 'System administrator',
}

export function IdentityAdministrationPanel({
  avatarEditor,
  user,
  administration,
}: {
  avatarEditor: ReactNode
  user?: UserProfile | null
  administration: ReturnTypeOfIdentityAdministration
}) {
  return (
    <div className="settings-submenu settings-submenu-info settings-identity-submenu">
      <div className="settings-submenu-title">Account status</div>
      <div className="settings-avatar-card">{avatarEditor}</div>
      <div className="settings-info-card">
        <strong>{user?.email || 'Signed in account'}</strong>
        <span>{user?.role ? roleLabels[user.role as GlobalRole] || user.role : 'Authenticated user'}</span>
      </div>

      <section className="identity-section">
        <header><strong>Access sessions</strong><span>{administration.sessions.length}</span></header>
        {administration.sessions.map((session) => (
          <div className="identity-row" key={session.session_id}>
            <div>
              <strong>{session.user_agent || 'Browser session'}</strong>
              <span>{session.status} · last seen {formatTime(session.last_seen_at)}</span>
            </div>
            {session.status === 'active' ? (
              <button
                className="identity-action"
                disabled={administration.pending}
                onClick={() => void administration.revokeSession(session.session_id)}
                type="button"
              >
                Revoke
              </button>
            ) : null}
          </div>
        ))}
      </section>

      {user?.role === 'platform_admin' ? (
        <section className="identity-section">
          <header><strong>User accounts</strong><span>{administration.users.length}</span></header>
          {administration.users.map((account) => (
            <div className="identity-row identity-user-row" key={account.id}>
              <div>
                <strong>{account.display_name}</strong>
                <span>{account.email} · {account.active_session_count} active sessions</span>
              </div>
              <div className="identity-controls">
                <select
                  aria-label={`Role for ${account.email}`}
                  disabled={administration.pending}
                  onChange={(event) => void administration.updateRole(account.id, event.target.value as GlobalRole)}
                  value={account.role}
                >
                  {globalRoles.map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}
                </select>
                <button
                  className={account.status === 'active' ? 'identity-action warning' : 'identity-action'}
                  disabled={administration.pending}
                  onClick={() => changeStatus(account.id, account.status, administration.updateStatus)}
                  type="button"
                >
                  {account.status === 'active' ? 'Suspend' : 'Activate'}
                </button>
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {administration.loading ? <span className="settings-avatar-status">Loading identity state…</span> : null}
      {administration.error ? <span className="settings-avatar-status error">{administration.error.message}</span> : null}
    </div>
  )
}

function formatTime(value?: string | null): string {
  if (!value) return 'never'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function changeStatus(
  userId: string,
  status: AccountStatus,
  updateStatus: (userId: string, status: AccountStatus) => Promise<unknown>,
) {
  const nextStatus = status === 'active' ? 'suspended' : 'active'
  if (nextStatus === 'suspended' && !window.confirm('Suspend this account and revoke all active sessions?')) return
  void updateStatus(userId, nextStatus)
}

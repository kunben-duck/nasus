import type { ReactNode } from 'react'

import type { ReturnTypeOfIdentityAdministration } from './identityAdministrationTypes'
import type { AccountStatus, GlobalRole, UserProfile } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'


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
  const { locale, t, tx } = useI18n()
  return (
    <div className="settings-submenu settings-submenu-info settings-identity-submenu">
      <div className="settings-submenu-title">{t('Account status')}</div>
      <div className="settings-avatar-card">{avatarEditor}</div>
      <div className="settings-info-card">
        <strong>{user?.email || t('Signed in account')}</strong>
        <span>{user?.role ? tx(roleLabels[user.role as GlobalRole] || user.role) : t('Authenticated user')}</span>
      </div>

      <section className="identity-section">
        <header><strong>{t('Access sessions')}</strong><span>{administration.sessions.length}</span></header>
        {administration.sessions.map((session) => (
          <div className="identity-row" key={session.session_id}>
            <div>
              <strong>{session.user_agent || t('Browser session')}</strong>
              <span>{tx(session.status)} · {t('last seen {time}', { time: formatTime(session.last_seen_at, locale, t('never')) })}</span>
            </div>
            {session.status === 'active' ? (
              <button
                className="identity-action"
                disabled={administration.pending}
                onClick={() => void administration.revokeSession(session.session_id)}
                type="button"
              >
                {t('Revoke')}
              </button>
            ) : null}
          </div>
        ))}
      </section>

      {user?.role === 'platform_admin' ? (
        <section className="identity-section">
          <header><strong>{t('User accounts')}</strong><span>{administration.users.length}</span></header>
          {administration.users.map((account) => (
            <div className="identity-row identity-user-row" key={account.id}>
              <div>
                <strong>{account.display_name}</strong>
                <span>{account.email} · {t('{count} active sessions', { count: account.active_session_count })}</span>
              </div>
              <div className="identity-controls">
                <select
                  aria-label={t('Role for {email}', { email: account.email })}
                  disabled={administration.pending}
                  onChange={(event) => void administration.updateRole(account.id, event.target.value as GlobalRole)}
                  value={account.role}
                >
                  {globalRoles.map((role) => <option key={role} value={role}>{tx(roleLabels[role])}</option>)}
                </select>
                <button
                  className={account.status === 'active' ? 'identity-action warning' : 'identity-action'}
                  disabled={administration.pending}
                  onClick={() => changeStatus(account.id, account.status, administration.updateStatus, t('Suspend this account and revoke all active sessions?'))}
                  type="button"
                >
                  {account.status === 'active' ? t('Suspend') : t('Activate')}
                </button>
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {administration.loading ? <span className="settings-avatar-status">{t('Loading identity state…')}</span> : null}
      {administration.error ? <span className="settings-avatar-status error">{tx(administration.error.message)}</span> : null}
    </div>
  )
}

function formatTime(value: string | null | undefined, locale: 'en' | 'zh', emptyValue: string): string {
  if (!value) return emptyValue
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function changeStatus(
  userId: string,
  status: AccountStatus,
  updateStatus: (userId: string, status: AccountStatus) => Promise<unknown>,
  confirmation: string,
) {
  const nextStatus = status === 'active' ? 'suspended' : 'active'
  if (nextStatus === 'suspended' && !window.confirm(confirmation)) return
  void updateStatus(userId, nextStatus)
}

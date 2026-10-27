import { useState } from 'react'

import { useProjectMembership } from '../../../domains/platform/identity/useProjectMembership'
import type { ProjectRole } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'


const projectRoles: ProjectRole[] = ['viewer', 'tester', 'qa_lead', 'project_admin']
const projectRoleLabels: Record<ProjectRole, string> = {
  viewer: 'Viewer',
  tester: 'Tester',
  qa_lead: 'QA lead',
  project_admin: 'Project administrator',
}

export function ProjectMembersPanel({ projectId, projectName }: { projectId: string; projectName?: string }) {
  const { t, tx } = useI18n()
  const [query, setQuery] = useState('')
  const membership = useProjectMembership(projectId, query)
  const projectAdminCount = membership.members.filter(({ binding }) => binding.role === 'project_admin').length

  return (
    <div className="settings-submenu settings-submenu-info settings-members-submenu">
      <div className="settings-submenu-title">{t('Project members')}</div>
      <div className="settings-info-card">
        <strong>{projectName || projectId}</strong>
        <span>{t('Project roles govern visible facts, tools, approvals, and release actions.')}</span>
      </div>
      <label className="settings-field">
        <span className="settings-field-label">{t('Add by name or email')}</span>
        <input
          className="settings-field-control"
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('Search active accounts')}
          type="search"
          value={query}
        />
      </label>
      {query.trim().length >= 2 ? (
        <section className="identity-section">
          <header><strong>{t('Candidates')}</strong><span>{membership.searching ? t('Searching') : membership.candidates.length}</span></header>
          {membership.candidates.map((candidate) => (
            <div className="identity-row" key={candidate.id}>
              <div><strong>{candidate.display_name}</strong><span>{candidate.email}</span></div>
              <button
                className="identity-action"
                disabled={membership.pending}
                onClick={() => void membership.assign(candidate.id)}
                type="button"
              >{t('Add')}</button>
            </div>
          ))}
        </section>
      ) : null}
      <section className="identity-section">
        <header><strong>{t('Current members')}</strong><span>{membership.members.length}</span></header>
        {membership.members.map(({ user, binding }) => {
          const lastProjectAdmin = binding.role === 'project_admin' && projectAdminCount === 1
          return (
            <div className="identity-row identity-user-row" key={binding.binding_id}>
              <div>
                <strong>{user.display_name}</strong>
                <span>{user.email}{lastProjectAdmin ? ` · ${t('last project administrator')}` : ''}</span>
              </div>
              <div className="identity-controls">
                <select
                  aria-label={t('Project role for {email}', { email: user.email })}
                  disabled={membership.pending || lastProjectAdmin}
                  onChange={(event) => void membership.changeRole(user.id, event.target.value as ProjectRole)}
                  value={binding.role}
                >
                  {projectRoles.map((role) => <option key={role} value={role}>{tx(projectRoleLabels[role])}</option>)}
                </select>
                <button
                  className="identity-action warning"
                  disabled={membership.pending || lastProjectAdmin}
                  onClick={() => void membership.revoke(user.id)}
                  type="button"
                >{t('Remove')}</button>
              </div>
            </div>
          )
        })}
      </section>
      {membership.loading ? <span className="settings-avatar-status">{t('Loading members…')}</span> : null}
      {membership.error ? <span className="settings-avatar-status error">{tx(membership.error.message)}</span> : null}
    </div>
  )
}

import { useState } from 'react'

import { useProjectMembership } from '../../../domains/platform/identity/useProjectMembership'
import type { ProjectRole } from '../../../domains/platform/types'


const projectRoles: ProjectRole[] = ['viewer', 'tester', 'qa_lead', 'project_admin']
const projectRoleLabels: Record<ProjectRole, string> = {
  viewer: 'Viewer',
  tester: 'Tester',
  qa_lead: 'QA lead',
  project_admin: 'Project administrator',
}

export function ProjectMembersPanel({ projectId, projectName }: { projectId: string; projectName?: string }) {
  const [query, setQuery] = useState('')
  const membership = useProjectMembership(projectId, query)
  const projectAdminCount = membership.members.filter(({ binding }) => binding.role === 'project_admin').length

  return (
    <div className="settings-submenu settings-submenu-info settings-members-submenu">
      <div className="settings-submenu-title">Project members</div>
      <div className="settings-info-card">
        <strong>{projectName || projectId}</strong>
        <span>Project roles govern visible facts, tools, approvals, and release actions.</span>
      </div>
      <label className="settings-field">
        <span className="settings-field-label">Add by name or email</span>
        <input
          className="settings-field-control"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search active accounts"
          type="search"
          value={query}
        />
      </label>
      {query.trim().length >= 2 ? (
        <section className="identity-section">
          <header><strong>Candidates</strong><span>{membership.searching ? 'Searching' : membership.candidates.length}</span></header>
          {membership.candidates.map((candidate) => (
            <div className="identity-row" key={candidate.id}>
              <div><strong>{candidate.display_name}</strong><span>{candidate.email}</span></div>
              <button
                className="identity-action"
                disabled={membership.pending}
                onClick={() => void membership.assign(candidate.id)}
                type="button"
              >Add</button>
            </div>
          ))}
        </section>
      ) : null}
      <section className="identity-section">
        <header><strong>Current members</strong><span>{membership.members.length}</span></header>
        {membership.members.map(({ user, binding }) => {
          const lastProjectAdmin = binding.role === 'project_admin' && projectAdminCount === 1
          return (
            <div className="identity-row identity-user-row" key={binding.binding_id}>
              <div>
                <strong>{user.display_name}</strong>
                <span>{user.email}{lastProjectAdmin ? ' · last project administrator' : ''}</span>
              </div>
              <div className="identity-controls">
                <select
                  aria-label={`Project role for ${user.email}`}
                  disabled={membership.pending || lastProjectAdmin}
                  onChange={(event) => void membership.changeRole(user.id, event.target.value as ProjectRole)}
                  value={binding.role}
                >
                  {projectRoles.map((role) => <option key={role} value={role}>{projectRoleLabels[role]}</option>)}
                </select>
                <button
                  className="identity-action warning"
                  disabled={membership.pending || lastProjectAdmin}
                  onClick={() => void membership.revoke(user.id)}
                  type="button"
                >Remove</button>
              </div>
            </div>
          )
        })}
      </section>
      {membership.loading ? <span className="settings-avatar-status">Loading members…</span> : null}
      {membership.error ? <span className="settings-avatar-status error">{membership.error.message}</span> : null}
    </div>
  )
}

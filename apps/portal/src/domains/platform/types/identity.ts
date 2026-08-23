export type GlobalRole = 'viewer' | 'tester' | 'qa_lead' | 'platform_admin'
export type ProjectRole = 'viewer' | 'tester' | 'qa_lead' | 'project_admin'
export type AccountStatus = 'active' | 'suspended'

export interface UserAdministrationRecord {
  id: string
  email: string
  display_name: string
  role: GlobalRole
  status: AccountStatus
  avatar_preset?: string | null
  avatar_image: boolean
  created_at: string
  updated_at: string
  last_login_at?: string | null
  active_session_count: number
}

export interface UserAdministrationPage {
  items: UserAdministrationRecord[]
  total: number
  limit: number
  offset: number
}

export interface AccessSessionView {
  session_id: string
  user_id: string
  status: 'active' | 'revoked' | 'expired'
  created_at: string
  expires_at: string
  revoked_at?: string | null
  last_seen_at?: string | null
  user_agent?: string | null
}

export interface ProjectRoleBinding {
  binding_id: string
  project_id: string
  user_id: string
  role: ProjectRole
  status: 'active' | 'revoked'
  scope_ref: string
  created_at: string
  updated_at: string
  created_by: string
}

export interface ProjectMemberView {
  user: UserAdministrationRecord
  binding: ProjectRoleBinding
}

export interface ProjectMemberCandidate {
  id: string
  email: string
  display_name: string
  avatar_preset?: string | null
  avatar_image: boolean
}

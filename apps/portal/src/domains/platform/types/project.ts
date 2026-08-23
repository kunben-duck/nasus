export interface ProjectCard {
  id: string
  name: string
  code: string
  summary: string
  status: string
  risk: string
  progress: number
  active_version: string
  blocked_items: number
  pending_approvals: number
  system_image_status: string
  preview_only?: boolean
}

export interface BuildData {
  drafts: ProjectCard[]
  imports_health: string[]
  provider_health: string
}

export interface DashboardData {
  active_projects: number
  running_versions: number
  blocked_items: number
  pending_approvals: number
  failed_runs: number
  projects: ProjectCard[]
}

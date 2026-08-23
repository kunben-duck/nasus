export interface VersionSummary {
  id: string
  name: string
  status: string
  branch_name: string
  us_total: number
  us_closed: number
  pending_runs: number
  pending_approvals: number
}

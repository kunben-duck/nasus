import type { ConversationSession } from '../agent/types'
import type { VersionSummary } from '../quality-loop/types'
import type { ProjectCard } from './types'

export interface WelcomeData {
  recent_projects: ProjectCard[]
  recent_versions: VersionSummary[]
  recent_conversations: ConversationSession[]
}

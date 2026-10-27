import type { GenerationArchive } from './testDesignGeneration'

export interface ReviewDraftRequest { project_id: string; after_id: string; limit: number }
export interface ReviewDraftItem {
  metadata: GenerationArchive['metadata']
  context_pin: GenerationArchive['result']['context_pin']
  scope_pin: GenerationArchive['result']['scope_pin']
}
export interface ReviewDraftPage {
  request: ReviewDraftRequest; items: ReviewDraftItem[]; next_after_id: string | null
  can_review: true; generation_authorized: false; execution_authorized: false
}

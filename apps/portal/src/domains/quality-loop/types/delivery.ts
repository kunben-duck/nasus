export interface IterationImageBinding {
  publication_id: string
  image_revision_id: string
  image_artifact_hash: string
  expected_head_id: string
}

export interface IterationCreateInput {
  project_id: string
  name: string
  image_binding: IterationImageBinding
}

export interface IterationCreateAttempt {
  actor_id: string
  idempotency_key: string
  input: IterationCreateInput
  invocation_id?: string
}

export interface DeliveryImagePin {
  publication_id: string
  baseline_id: string
  image_revision_id: string
  image_artifact_hash: string
  manifest_id: string
  manifest_hash: string
  sequence: number
  quality_generation_authorized: false
  release_authorized: false
}

export interface VersionDelivery {
  project_id: string
  version_id: string
  name: string
  enabled: boolean
  stage: 'legacy' | 'image_pinned'
  baseline: DeliveryImagePin | null
  iteration_image: DeliveryImagePin | null
  code_revisions: { binding_id: string; source_id: string; source_revision_id: string; repository: string;
    tracked_ref: string | null; external_revision: string; commit_sha: string | null; content_hash: string; manifest_hash: string }[]
  blockers: string[]
  pending_confirmations: string[]
  available_actions: 'view_pinned_image'[]
}

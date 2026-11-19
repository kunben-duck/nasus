import type { VersionDelivery } from './types/delivery'
import { deliveryHash, deliveryId } from './iterationCreation'

export type IterationImageOption = { request: { project_id: string; version_id: string; expected_image_revision_id: string;
  expected_image_artifact_hash: string; image_revision_id: string; image_artifact_hash: string; code_commits: Record<string, string> };
  code_revisions: VersionDelivery['code_revisions']; adoption_authorized: false }

export function verifyImageAdoption(value: IterationImageOption, view: VersionDelivery, selected: string) {
  const input = value?.request, code = value?.code_revisions
  if (!input || value.adoption_authorized !== false || !view.enabled || !view.iteration_image
      || input.project_id !== view.project_id || input.version_id !== view.version_id
      || input.image_revision_id !== selected || !deliveryId(selected) || selected === view.iteration_image.image_revision_id
      || !deliveryHash(input.image_artifact_hash) || input.expected_image_revision_id !== view.iteration_image.image_revision_id
      || input.expected_image_artifact_hash !== view.iteration_image.image_artifact_hash
      || !Array.isArray(code) || !code.length || code.length !== view.code_revisions.length
      || !input.code_commits || Array.isArray(input.code_commits) || Object.keys(input.code_commits).length !== code.length
      || new Set(code.map((item) => item.binding_id)).size !== code.length
      || code.some((item) => {
        const old = view.code_revisions.find((prior) => prior.binding_id === item.binding_id)
        return !old || item.repository !== old.repository || item.source_id !== old.source_id
          || item.tracked_ref !== old.tracked_ref || !deliveryId(item.source_revision_id)
          || !item.commit_sha || !/^[0-9a-f]{40}$/.test(item.commit_sha) || item.external_revision !== item.commit_sha
          || input.code_commits[item.binding_id] !== item.commit_sha || !deliveryHash(item.content_hash) || !deliveryHash(item.manifest_hash)
      })) throw new Error('Image adoption scope mismatch')
  return value
}

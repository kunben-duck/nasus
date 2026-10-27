import { imageRevisionApi } from './imageRevisionApi'
import type { ImageRevisionSummary } from './types/imageRevision'

export interface FrozenImageSources {
  project_id: string; image_revision_id: string; image_artifact_hash: string; manifest_id: string; manifest_hash: string
  source_members: { binding_id: string; source_type: string; source_revision_id: string | null; status: string }[]
}
const id = (value: unknown) => typeof value === 'string' && /^[^\s]{1,128}$/.test(value)
  && [...value].every((char) => char.charCodeAt(0) > 32 && char.charCodeAt(0) !== 127)
const hash = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
function requireSources(condition: unknown): asserts condition { if (!condition) throw new Error('Frozen source scope could not be verified') }

export async function readFrozenImageSources(pin: Pick<ImageRevisionSummary, 'project_id' | 'image_revision_id' | 'artifact_hash'>,
  signal: AbortSignal): Promise<FrozenImageSources> {
  const members: FrozenImageSources['source_members'] = []
  let offset = 0, first: Awaited<ReturnType<typeof imageRevisionApi.page>> | undefined
  for (;;) {
    signal.throwIfAborted()
    const page = await imageRevisionApi.page(pin.project_id, pin.image_revision_id, { section: 'source_members', offset }, signal, 25)
    requireSources(page.section === 'source_members' && page.revision.project_id === pin.project_id
      && page.revision.image_revision_id === pin.image_revision_id && page.revision.artifact_hash === pin.artifact_hash
      && hash(page.revision.manifest_hash) && id(page.revision.manifest_id) && Number.isSafeInteger(page.total) && page.total > 0 && page.total <= 1000
      && (!first || JSON.stringify(page.revision) === JSON.stringify(first.revision) && page.total === first.total))
    first ??= page
    requireSources(page.items.length <= 25 && offset + page.items.length <= page.total
      && page.next_offset === (offset + page.items.length < page.total ? offset + page.items.length : null)
      && (page.items.length > 0 || offset === page.total))
    for (const item of page.items) {
      requireSources(id(item.binding_id) && typeof item.source_type === 'string'
        && ['captured', 'failed', 'pending', 'legacy_unverified'].includes(item.status)
        && (item.status === 'captured' ? id(item.source_revision_id) : item.source_revision_id === null)
        && !members.some((prior) => prior.binding_id === item.binding_id))
      members.push(item)
    }
    if (page.next_offset === null) break
    offset = page.next_offset
  }
  signal.throwIfAborted()
  return { project_id: pin.project_id, image_revision_id: first!.revision.image_revision_id, image_artifact_hash: first!.revision.artifact_hash,
    manifest_id: first!.revision.manifest_id, manifest_hash: first!.revision.manifest_hash, source_members: members }
}

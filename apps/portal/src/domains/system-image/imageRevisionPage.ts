import { imageRevisionApi } from './imageRevisionApi'
import { imageRevisionRows, requireMatchingMembers } from './imageRevisionView'
import { isImagePageSizeError, readImagePair } from './imageReadPair'
import type { ImagePageSelection } from './types/imageRevision'

export async function loadImageRevisionPage(projectId: string, revisionId: string, selection: ImagePageSelection, signal: AbortSignal) {
  let limit = 25
  for (;;) {
    signal.throwIfAborted()
    try {
      if (selection.section === 'objects') {
        const [page, memberPage] = await readImagePair(
          () => imageRevisionApi.page(projectId, revisionId, selection, signal, limit),
          () => imageRevisionApi.page(projectId, revisionId, { ...selection, section: 'members' }, signal, limit), signal)
        if (page.section !== 'objects') throw new Error('Frozen image section mismatch')
        // Both independently authorized pages must match, including after a
        // size reduction. Never display one side while the other is pending.
        const members = requireMatchingMembers(page, memberPage)
        return { revision: page.revision, total: page.total, nextOffset: page.next_offset, rows: imageRevisionRows(page, members) }
      }
      const page = await imageRevisionApi.page(projectId, revisionId, selection, signal, limit)
      signal.throwIfAborted()
      return { revision: page.revision, total: page.total, nextOffset: page.next_offset, rows: imageRevisionRows(page) }
    } catch (error) {
      // This is a smaller read, never a retry of a failed mutation or authorization.
      if (!isImagePageSizeError(error) || limit === 1) throw error
      limit = Math.max(1, Math.floor(limit / 2))
    }
  }
}

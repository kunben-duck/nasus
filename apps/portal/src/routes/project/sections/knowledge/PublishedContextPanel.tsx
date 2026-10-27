import { useId, useState } from 'react'
import type { SystemImageData } from '../../../../domains/system-image/types'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { ContextPackPanel } from './revisions/ContextPackPanel'

export function PublishedContextPanel({ projectId, pin }: {
  projectId: string; pin: NonNullable<NonNullable<SystemImageData['read_state']>['pin']>
}) {
  const sessionId = useId(), [failed, setFailed] = useState(false), { t } = useI18n()
  if (failed) return <p role="alert">{t('Published context could not be verified. Reload the knowledge page to check the head and source access.')}</p>
  return <ContextPackPanel scope={{ projectId, sessionId, onFailure: setFailed }}
    revisionId={pin.image_revision_id} imageHash={pin.image_artifact_hash} publicationId={pin.publication_id} />
}

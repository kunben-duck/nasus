import { useState } from 'react'
import type { ReferenceAssertion } from '../../../../../domains/system-image/referenceReviewApi'
import { useReferencePage } from '../../../../../domains/system-image/useReferenceReviews'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { ReferenceReadPin } from '../../../../../domains/system-image/referencePageRead'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ReferenceDecisionEditor } from './ReferenceDecisionEditor'

export function ReferenceCandidates({ scope, revisionId, proposalId, pin }: {
  scope: ImageReadScope; revisionId: string; proposalId: string; pin: ReferenceReadPin
}) {
  const { t } = useI18n()
  const [paging, setPaging] = useState<{ section: 'assertions' | 'gaps'; offsets: number[] }>({ section: 'assertions', offsets: [0] })
  const [chosen, setChosen] = useState<ReferenceAssertion | null>(null)
  const query = useReferencePage(scope, revisionId, proposalId, paging.section, paging.offsets.at(-1)!, pin)
  return <>
    <div className="segmented"><button type="button" aria-pressed={paging.section === 'assertions'} onClick={() => { setPaging({ section: 'assertions', offsets: [0] }); setChosen(null) }}>{t('References')}</button>
      <button type="button" aria-pressed={paging.section === 'gaps'} onClick={() => { setPaging({ section: 'gaps', offsets: [0] }); setChosen(null) }}>{t('Reference gaps')}</button></div>
    {query.isError ? null : query.isPending || query.isFetching ? <p role="status">{t('Checking source access...')}</p> : <>
      <p>{t('{references} references · {gaps} gaps', { references: query.data.assertion_count, gaps: query.data.gap_count })}</p>
      {query.data.items.map((item, i) => <div key={i} className="reference-candidate-row">
        <span>{item.reference_id}</span>{'assertion_id' in item
          ? <button type="button" onClick={() => setChosen(item)}>{t('Inspect reference')}</button>
          : <code>{item.reason}</code>}
      </div>)}
      <AnalysisPagination label={t('Reference content pages')} page={paging.offsets.length}
        previous={paging.offsets.length > 1 ? () => { setPaging({ ...paging, offsets: paging.offsets.slice(0, -1) }); setChosen(null) } : undefined}
        next={query.data.next_offset !== null ? () => { setPaging({ ...paging, offsets: [...paging.offsets, query.data.next_offset!] }); setChosen(null) } : undefined} />
      {chosen && <ReferenceDecisionEditor key={chosen.assertion_id} scope={scope} revisionId={revisionId} proposalId={proposalId} assertion={chosen}
        parentArtifactHash={pin.imageArtifactHash} proposalDigest={pin.proposalDigest} />}
    </>}
  </>
}

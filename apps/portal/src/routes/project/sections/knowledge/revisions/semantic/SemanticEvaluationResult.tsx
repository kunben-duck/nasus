import { useState } from 'react'
import type { LinkCandidatePage } from '../../../../../../domains/system-image/linkCandidateApi'
import type { ImageReadScope } from '../../../../../../domains/system-image/useImageRevisions'
import type { SemanticCitation, SemanticResult, SemanticSpan } from '../../../../../../domains/system-image/types/semanticEvaluation'
import { useI18n } from '../../../../../../shared/i18n/I18nProvider'
import { ReferenceExcerpt } from '../ReferenceEvidence'
import { SemanticRelationReview } from './SemanticRelationReview'

export function SemanticEvaluationResult({ scope, page, result }: { scope: ImageReadScope; page: LinkCandidatePage; result: SemanticResult }) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<SemanticSpan | null>(null)
  const [reviewing, setReviewing] = useState<string | null>(null)
  const assessment = { supports: t('Supports (proposed)'), contradicts: t('Contradicts (proposed)'),
    unrelated: t('Unrelated (proposed)'), unknown: t('Unknown (proposed)') }
  return <section className="semantic-result" aria-label={t('Archived semantic evaluation')}>
    <h4>{t('Proposed inference only')}</h4>
    <p>{t('Pending confirmation. Not an approved business oracle.')}</p>
    <p>{t('Model judgments remain proposed. Human relation decisions are recorded separately and never prove coverage or publish an image.')}</p>
    {result.evaluation.judgments.map((item) => <article className="semantic-judgment" key={item.subject_object_id}>
      <header><strong>{page.items.find((candidate) => candidate.endpoint.object_id === item.subject_object_id)?.endpoint.title ?? item.subject_object_id}</strong>
        <span>{assessment[item.assessment]}</span></header>
      <p>{item.reason_summary}</p>
      <p>{t('Pinned revision')}: <code>{item.subject_revision_id}</code></p>
      {item.evidence.length > 0 && <h5>{t('Quoted evidence')}</h5>}
      {item.evidence.map((quote) => <Citation key={`${quote.span_id}:${quote.start}`} quote={quote} spans={result.spans} inspect={setSelected} />)}
      {item.counterevidence.length > 0 && <h5>{t('Quoted counterevidence')}</h5>}
      {item.counterevidence.map((quote) => <Citation key={`${quote.span_id}:${quote.start}`} quote={quote} spans={result.spans} inspect={setSelected} />)}
      {item.unknowns.length > 0 && <><h5>{t('Unresolved information')}</h5><ul>{item.unknowns.map((unknown, index) => <li key={index}>{unknown}</li>)}</ul></>}
      {item.oracle && <><h5>{t('Proposed expected result')}</h5><p>{item.oracle.expected_value}</p></>}
      <button className="small-btn" onClick={() => setReviewing(item.subject_object_id)}>{t('Review relation')}</button>
      {reviewing === item.subject_object_id && <SemanticRelationReview scope={scope} result={result} subject={item} />}
    </article>)}
    {selected && <section className="semantic-evidence-inspection"><h5>{t('Pinned source evidence')}</h5>
      <ReferenceExcerpt key={selected.span_id} scope={scope} revisionId={page.image_revision_id} objectId={selected.object_id} evidenceId={selected.evidence_id} />
    </section>}
  </section>
}

function Citation({ quote, spans, inspect }: { quote: SemanticCitation; spans: SemanticSpan[]; inspect: (span: SemanticSpan) => void }) {
  const { t } = useI18n()
  const span = spans.find((item) => item.span_id === quote.span_id)!
  return <blockquote className="semantic-citation"><pre>{quote.quote}</pre>
    <p>{span.relative_path}:{span.start_line}-{span.end_line}</p>
    <p>{span.basis === 'projected_field' ? t('Parsed document field; character offsets refer to the field, not the raw source row.')
      : t('Source excerpt; character offsets refer to the archived excerpt.')}</p>
    <p>{t('Character range')}: {quote.start}-{quote.end}</p>
    <button className="small-btn" onClick={() => inspect(span)}>{t('Inspect archived evidence')}</button>
  </blockquote>
}

import type { SourceBindingCardConfig, SourceBindingSource } from './sourceBindingCards'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function SourceBindingCard({
  card,
  value,
  source,
  onChange,
  onUpload,
  uploading,
  trackedRef,
  onTrackedRefChange,
}: {
  card: SourceBindingCardConfig
  value: string
  source?: SourceBindingSource
  onChange: (value: string) => void
  onUpload: (files: File[]) => void
  uploading: boolean
  trackedRef?: string
  onTrackedRefChange?: (value: string) => void
}) {
  const { t, tx } = useI18n()
  const status = source?.ingestion_status ?? 'missing'
  const evidenceCount = source?.evidence_refs.length ?? 0

  return (
    <article className={`source-binding-card ${status}`}>
      <div className="source-binding-card-head">
        <span className="material-symbols-outlined source-binding-icon" aria-hidden="true">{card.icon}</span>
        <div>
          <strong>
            {tx(card.label)}
            <span className="source-requirement-label">{card.required ? t('Required') : t('Optional')}</span>
          </strong>
          <p>{tx(card.detail)}</p>
        </div>
        <span className={`source-status-pill ${status}`}>{tx(status)}</span>
      </div>
      <div className="source-field-row">
        <input
          aria-label={t('{label} source URI', { label: tx(card.label) })}
          className="source-field-control"
          type="text"
          value={value}
          placeholder={tx(card.placeholder)}
          onChange={(event) => onChange(event.target.value)}
          data-testid={card.testId}
        />
        {!card.required ? (
          <label className={`source-upload-button ${uploading ? 'loading' : ''}`}>
            <span className="material-symbols-outlined" aria-hidden="true">upload_file</span>
            {uploading ? t('Uploading...') : t('Upload files')}
            <input
              className="source-file-input"
              type="file"
              multiple
              disabled={uploading}
              data-testid={`${card.testId}-file`}
              onChange={(event) => {
                onUpload(Array.from(event.currentTarget.files ?? []))
                event.currentTarget.value = ''
              }}
            />
          </label>
        ) : null}
      </div>
      {onTrackedRefChange ? (
        <label className="source-tracked-ref-field">
          <span>{t('Git branch or tag')}</span>
          <input className="source-field-control" type="text" value={trackedRef ?? ''}
            aria-label={t('Git branch or tag')}
            placeholder={t('refs/heads/main')}
            data-testid="source-code-tracked-ref"
            onChange={(event) => onTrackedRefChange(event.target.value)} />
        </label>
      ) : null}
      <div className="source-binding-meta">
        <span>{source?.content_hash ? source.content_hash.slice(0, 18) : t('No hash yet')}</span>
        <span>{t('{count} evidence refs', { count: evidenceCount })}</span>
      </div>
    </article>
  )
}

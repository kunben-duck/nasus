import type { SourceBindingCardConfig, SourceBindingSource } from './sourceBindingCards'

export function SourceBindingCard({
  card,
  value,
  source,
  onChange,
  onUpload,
  uploading,
}: {
  card: SourceBindingCardConfig
  value: string
  source?: SourceBindingSource
  onChange: (value: string) => void
  onUpload: (files: File[]) => void
  uploading: boolean
}) {
  const status = source?.ingestion_status ?? 'missing'
  const evidenceCount = source?.evidence_refs.length ?? 0

  return (
    <article className={`source-binding-card ${status}`}>
      <div className="source-binding-card-head">
        <span className="material-symbols-outlined source-binding-icon" aria-hidden="true">{card.icon}</span>
        <div>
          <strong>
            {card.label}
            <span className="source-requirement-label">{card.required ? 'Required' : 'Optional'}</span>
          </strong>
          <p>{card.detail}</p>
        </div>
        <span className={`source-status-pill ${status}`}>{status}</span>
      </div>
      <div className="source-field-row">
        <input
          aria-label={`${card.label} source URI`}
          className="source-field-control"
          type="text"
          value={value}
          placeholder={card.placeholder}
          onChange={(event) => onChange(event.target.value)}
          data-testid={card.testId}
        />
        {!card.required ? (
          <label className={`source-upload-button ${uploading ? 'loading' : ''}`}>
            <span className="material-symbols-outlined" aria-hidden="true">upload_file</span>
            {uploading ? 'Uploading...' : 'Upload files'}
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
      <div className="source-binding-meta">
        <span>{source?.content_hash ? source.content_hash.slice(0, 18) : 'No hash yet'}</span>
        <span>{evidenceCount} evidence refs</span>
      </div>
    </article>
  )
}

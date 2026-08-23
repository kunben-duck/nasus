import type { SystemImageData } from '../../../domains/system-image/types'
import type { SourceBindingValues } from './sourceBindingDefaults'
import type { SourceBindingKey } from './sourceBindingCards'
import { SourceBindingCard } from './SourceBindingCard'
import { sourceBindingCards, sourceMapByType } from './sourceBindingCards'

export function SourceBindingPanel({
  systemImage,
  values,
  error,
  loading,
  onChange,
  onUpload,
  uploadingSourceKey,
  onSubmit,
}: {
  systemImage?: SystemImageData
  values: SourceBindingValues
  error: string | null
  loading: boolean
  onChange: (key: keyof SourceBindingValues, value: string) => void
  onUpload: (key: SourceBindingKey, files: File[]) => void
  uploadingSourceKey?: SourceBindingKey
  onSubmit: () => void
}) {
  const sourceByType = sourceMapByType(systemImage)
  const missing = systemImage?.build_state.missing_source_types ?? []
  const ready = systemImage?.build_state.status === 'ready'

  return (
    <div className="source-binding-panel" data-testid="source-binding-panel">
      <div className="source-binding-header">
        <div>
          <span className="eyebrow">Source bindings</span>
          <strong>{ready ? 'System image sources are live' : 'Connect system image sources'}</strong>
          <p>
            Code is required to initialize the system image. Historical US documents and test assets are optional
            enrichment sources. Registration and ingestion still execute through the same audited tool contract.
          </p>
        </div>
        <span className={`source-status-pill ${ready ? 'indexed' : missing.length ? 'missing' : 'pending'}`}>
          {ready ? 'ready' : missing.length ? 'source required' : systemImage?.build_state.status ?? 'draft'}
        </span>
      </div>
      <div className="source-binding-grid">
        {sourceBindingCards.map((card) => (
          <SourceBindingCard
            card={card}
            key={card.key}
            value={values[card.key]}
            source={sourceByType.get(card.sourceType)}
            onChange={(value) => onChange(card.key, value)}
            onUpload={(files) => onUpload(card.key, files)}
            uploading={uploadingSourceKey === card.key}
          />
        ))}
      </div>
      {error ? <div className="source-binding-error" role="alert">{error}</div> : null}
      <div className="source-build-actions">
        <button
          className="composer-action-button build-submit-button"
          data-testid="build-system-image-with-sources"
          type="button"
          onClick={onSubmit}
          disabled={loading || Boolean(uploadingSourceKey)}
        >
          <span className="material-symbols-outlined action-spark" aria-hidden="true">auto_awesome</span>
          {loading ? 'Building system image...' : ready ? 'Rebuild system image' : 'Build system image'}
        </button>
      </div>
    </div>
  )
}

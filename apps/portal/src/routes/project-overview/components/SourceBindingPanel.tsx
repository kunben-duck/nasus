import type { SystemImageData } from '../../../domains/system-image/types'
import type { SourceBindingValues } from './sourceBindingDefaults'
import type { SourceBindingKey } from './sourceBindingCards'
import { SourceBindingCard } from './SourceBindingCard'
import { sourceBindingCards, sourceMapByType } from './sourceBindingCards'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { SourceVisibilityNotice } from '../../../shared/ui/SourceVisibilityNotice'

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
  const { t, tx } = useI18n()
  const sourceByType = sourceMapByType(systemImage)
  const missing = systemImage?.build_state.missing_source_types ?? []
  const ready = systemImage?.build_state.status === 'ready'

  if (systemImage?.visibility?.mode === 'source_filtered') return <SourceVisibilityNotice limited />

  return (
    <div className="source-binding-panel" data-testid="source-binding-panel">
      <div className="source-binding-header">
        <div>
          <span className="eyebrow">{t('Source bindings')}</span>
          <strong>{ready ? t('System image sources are live') : t('Connect system image sources')}</strong>
          <p>{t('Code is required to initialize the system image. Historical US documents and test assets are optional enrichment sources. Registration and ingestion still execute through the same audited tool contract.')}</p>
        </div>
        <span className={`source-status-pill ${ready ? 'indexed' : missing.length ? 'missing' : 'pending'}`}>
          {ready ? t('ready') : missing.length ? t('source required') : tx(systemImage?.build_state.status ?? 'draft')}
        </span>
      </div>
      <div className="source-binding-grid">
        {sourceBindingCards.map((card) => (
          <SourceBindingCard
            card={card}
            key={card.key}
            value={values[card.key]}
            trackedRef={card.key === 'code' ? values.codeRef ?? '' : undefined}
            onTrackedRefChange={card.key === 'code' ? (value) => onChange('codeRef', value) : undefined}
            source={sourceByType.get(card.sourceType)}
            onChange={(value) => onChange(card.key, value)}
            onUpload={(files) => onUpload(card.key, files)}
            uploading={uploadingSourceKey === card.key}
          />
        ))}
      </div>
      {error ? <div className="source-binding-error" role="alert">{tx(error)}</div> : null}
      <div className="source-build-actions">
        <button
          className="composer-action-button build-submit-button"
          data-testid="build-system-image-with-sources"
          type="button"
          onClick={onSubmit}
          disabled={loading || Boolean(uploadingSourceKey)}
        >
          <span className="material-symbols-outlined action-spark" aria-hidden="true">auto_awesome</span>
          {loading ? t('Building system image...') : ready ? t('Rebuild system image') : t('Build system image')}
        </button>
      </div>
    </div>
  )
}

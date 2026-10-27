import type { ModelRoute, ModelRouteConfigurations, SavedModelConfig } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ModelConfigurationList({
  route,
  configuration,
  disabled,
  onAdd,
  onEdit,
  onActivateModel,
  onUseSystemDefaultModel,
}: {
  route: ModelRoute
  configuration?: ModelRouteConfigurations
  disabled: boolean
  onAdd: () => void
  onEdit: (config: SavedModelConfig) => void
  onActivateModel: (configId: string) => void
  onUseSystemDefaultModel: (route: ModelRoute) => void
}) {
  const { t } = useI18n()
  const saved = configuration?.configurations ?? []
  const systemActive = (configuration?.active_source ?? 'system_default') === 'system_default'
  const routeLabel = route === 'chat' ? t('LLM') : route === 'embedding' ? t('Embedding') : t('Rerank')

  return (
    <div className="model-config-list">
      <div className="model-config-list-header">
        <div>
          <strong>{t('{route} models', { route: routeLabel })}</strong>
          <span>{t('{count} custom models saved', { count: saved.length })}</span>
        </div>
        <button className="settings-save-button" disabled={disabled} onClick={onAdd} type="button">{t('Add model')}</button>
      </div>
      <div className={`model-config-card ${systemActive ? 'active' : ''}`}>
        <div>
          <strong>{t('System default')}</strong>
          <span>{systemActive ? t('Currently active') : t('Use deployment default model')}</span>
        </div>
        <div className="model-config-card-actions">
          {systemActive ? <span className="settings-provider-pill live">{t('active')}</span> : (
            <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onUseSystemDefaultModel(route)} type="button">{t('Use as active')}</button>
          )}
        </div>
      </div>
      {saved.map((config) => (
        <div className={`model-config-card ${config.active ? 'active' : ''}`} key={config.config_id}>
          <div>
            <strong>{config.display_name}</strong>
            <span>{config.active ? t('Currently active') : t('Saved custom model')}</span>
          </div>
          <div className="model-config-card-actions">
            {config.active ? <span className="settings-provider-pill live">{t('active')}</span> : (
              <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onActivateModel(config.config_id)} type="button">{t('Use as active')}</button>
            )}
            <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onEdit(config)} type="button">{t('Edit')}</button>
          </div>
        </div>
      ))}
      {saved.length === 0 ? <div className="model-config-empty">{t('No custom model saved yet. Add and test a model to make it available.')}</div> : null}
    </div>
  )
}

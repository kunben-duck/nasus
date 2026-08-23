import type { ModelRoute, ModelRouteConfigurations, SavedModelConfig } from '../../../domains/platform/types'
import { modelRouteLabel } from '../../../domains/platform/settings/modelProfiles'

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
  const saved = configuration?.configurations ?? []
  const systemActive = (configuration?.active_source ?? 'system_default') === 'system_default'

  return (
    <div className="model-config-list">
      <div className="model-config-list-header">
        <div>
          <strong>{modelRouteLabel(route)} models</strong>
          <span>{saved.length} custom model{saved.length === 1 ? '' : 's'} saved</span>
        </div>
        <button className="settings-save-button" disabled={disabled} onClick={onAdd} type="button">Add model</button>
      </div>
      <div className={`model-config-card ${systemActive ? 'active' : ''}`}>
        <div>
          <strong>System default</strong>
          <span>{systemActive ? 'Currently active' : 'Use deployment default model'}</span>
        </div>
        <div className="model-config-card-actions">
          {systemActive ? <span className="settings-provider-pill live">Active</span> : (
            <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onUseSystemDefaultModel(route)} type="button">Active</button>
          )}
        </div>
      </div>
      {saved.map((config) => (
        <div className={`model-config-card ${config.active ? 'active' : ''}`} key={config.config_id}>
          <div>
            <strong>{config.display_name}</strong>
            <span>{config.active ? 'Currently active' : 'Saved custom model'}</span>
          </div>
          <div className="model-config-card-actions">
            {config.active ? <span className="settings-provider-pill live">active</span> : (
              <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onActivateModel(config.config_id)} type="button">Active</button>
            )}
            <button className="settings-save-button secondary compact" disabled={disabled} onClick={() => onEdit(config)} type="button">Edit</button>
          </div>
        </div>
      ))}
      {saved.length === 0 ? <div className="model-config-empty">No custom model saved yet. Add and test a model to make it available.</div> : null}
    </div>
  )
}

import type { ModelRoute } from '../../../domains/platform/types'
import { modelRouteLabel } from '../../../domains/platform/settings/modelProfiles'
import { modelRoutes } from '../../../domains/platform/settings/useModelConfigurationDraft'

export function ModelRouteTabs({
  activeRoute,
  onActiveRouteChange,
}: {
  activeRoute: ModelRoute
  onActiveRouteChange: (route: ModelRoute) => void
}) {
  return (
    <div className="model-route-tabs">
      {modelRoutes.map((route) => (
        <button className={activeRoute === route ? 'active' : ''} key={route} onClick={() => onActiveRouteChange(route)} type="button">
          {modelRouteLabel(route)}
        </button>
      ))}
    </div>
  )
}

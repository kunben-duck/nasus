import type { ModelRoute } from '../../../domains/platform/types'
import { modelRoutes } from '../../../domains/platform/settings/useModelConfigurationDraft'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ModelRouteTabs({
  activeRoute,
  onActiveRouteChange,
}: {
  activeRoute: ModelRoute
  onActiveRouteChange: (route: ModelRoute) => void
}) {
  const { t } = useI18n()
  return (
    <div className="model-route-tabs">
      {modelRoutes.map((route) => (
        <button className={activeRoute === route ? 'active' : ''} key={route} onClick={() => onActiveRouteChange(route)} type="button">
          {route === 'chat' ? t('LLM') : route === 'embedding' ? t('Embedding') : t('Rerank')}
        </button>
      ))}
    </div>
  )
}

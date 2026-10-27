import type { ReactNode } from 'react'

import type { ModelRoute, StudioSettings } from '../../../domains/platform/types'
import { modelRouteLabel, profileFor } from '../../../domains/platform/settings/modelProfiles'
import { useI18n } from '../../../shared/i18n/I18nProvider'

const modelRoutes: ModelRoute[] = ['chat', 'embedding', 'rerank']

export function AccountStatusPanel({ avatarEditor }: { avatarEditor: ReactNode }) {
  return avatarEditor
}

export function ProviderStatusPanel({ settings }: { settings?: StudioSettings }) {
  const { t, tx } = useI18n()
  return (
    <div className="settings-submenu settings-submenu-info">
      <div className="settings-submenu-title">{t('Provider status')}</div>
      {modelRoutes.map((route) => {
        const profile = profileFor(settings, route)
        return (
          <div className="settings-info-card" key={route}>
            <strong>{tx(modelRouteLabel(route) === 'embedding' ? 'Embedding' : modelRouteLabel(route) === 'rerank' ? 'Rerank' : 'LLM')}</strong>
            <span>{profile.model_provider} · {profile.model_name}</span>
            <span className={`settings-provider-pill ${profile.runtime_mode === 'live' ? 'live' : 'fallback'}`}>{tx(profile.runtime_mode)}</span>
          </div>
        )
      })}
    </div>
  )
}

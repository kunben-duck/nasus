import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '../../../apps/portal/src/shared/i18n/I18nProvider'
import { authUserQueryKey } from '../../../apps/portal/src/domains/platform/useAuthSession'
import { HttpFixtureHistoryPanel } from '../../../apps/portal/src/routes/project/sections/knowledge/scope/HttpFixtureHistoryPanel'
import '../../../apps/portal/src/styles/app.css'
import '../http-fixture/surface.css'

const params = new URLSearchParams(location.search)
document.documentElement.dataset.theme = params.get('theme') === 'light' ? 'light' : 'dark'
localStorage.setItem('nasus.locale', params.get('locale') === 'zh' ? 'zh' : 'en')
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
// Explicit UI identity specimen. It does not authenticate to any real backend.
client.setQueryData(authUserQueryKey, { id: 'independent-admin', name: 'Browser specimen', role: 'project_admin' })
function Surface() {
  return <main className="test-design-scope">
    <h1>Original fixture history browser contract</h1>
    <p>Production component with intercepted archive ports. Not real authentication, a production route, PG, Temporal, exweb or business coverage.</p>
    <HttpFixtureHistoryPanel projectId="p" />
  </main>
}
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}><I18nProvider><Surface /></I18nProvider></QueryClientProvider></StrictMode>)

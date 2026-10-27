import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '../../../apps/portal/src/shared/i18n/I18nProvider'
import { HttpFixtureOperationPanel } from '../../../apps/portal/src/routes/project/sections/knowledge/scope/HttpFixtureOperationPanel'
import '../../../apps/portal/src/styles/app.css'
import '../../../apps/portal/src/routes/project/sections/knowledge/scope/test-design-scope.css'
import '../../../apps/portal/src/routes/project/sections/knowledge/scope/run-plan.css'
import './surface.css'

const params = new URLSearchParams(location.search)
document.documentElement.dataset.theme = params.get('theme') === 'light' ? 'light' : 'dark'
localStorage.setItem('nasus.locale', params.get('locale') === 'zh' ? 'zh' : 'en')
const specimen = await fetch('/browser-specimen.json').then((response) => {
  if (!response.ok) throw new Error('Explicit browser transport specimen is required')
  return response.json()
})
const client = new QueryClient({ mutationCache: new MutationCache({ onError: (error) => console.error('Contract mutation error:', error.stack) }),
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
function Surface() {
  const [failed, setFailed] = useState(false)
  return <main className="test-design-scope">
    <h1>Fixture component browser contract</h1>
    <p>Explicit transport specimens only. Not a production-route, PostgreSQL, Temporal, target or business-coverage verification.</p>
    {failed ? <p role="alert" data-testid="parent-protection">Parent hid the protected operation after verification failed.</p>
      : <HttpFixtureOperationPanel plan={specimen.plan} recipe={specimen.recipe} actorId="admin" current onFailure={() => setFailed(true)} />}
  </main>
}
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}><I18nProvider><Surface /></I18nProvider></QueryClientProvider></StrictMode>)

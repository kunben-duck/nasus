import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '../../../apps/portal/src/shared/i18n/I18nProvider'
import { authUserQueryKey } from '../../../apps/portal/src/domains/platform/useAuthSession'
import { RunsSection } from '../../../apps/portal/src/routes/project/sections/RunsSection'
import { RunPlanCaseSetupPicker } from '../../../apps/portal/src/routes/project/sections/knowledge/scope/RunPlanCaseSetupPicker'
import '../../../apps/portal/src/styles/app.css'
import '../../../apps/portal/src/routes/project/sections/knowledge/scope/run-plan.css'
import '../http-fixture/surface.css'

const params = new URLSearchParams(location.search)
document.documentElement.dataset.theme = params.get('theme') === 'light' ? 'light' : 'dark'
localStorage.setItem('nasus.locale', params.get('locale') === 'zh' ? 'zh' : 'en')
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
// Explicit UI identity specimen. It does not authenticate to any real backend.
client.setQueryData(authUserQueryKey, { id: 'independent-admin', name: 'Browser specimen', role: 'project_admin' })
function SetupSurface({ hash }: { hash: string }) {
  const [setups, setSetups] = useState([{ caseId: 'case:0', commandId: '' }])
  const edit = (caseId: string, commandId: string) => setSetups((rows) => rows.map((row) => row.caseId === caseId ? { ...row, commandId } : row))
  return <main className="run-plan-panel run-plan-case-panel test-design-scope">
    <h1>Original case setup selection contract</h1>
    <RunPlanCaseSetupPicker plan={{ project_id: 'p', run_plan_id: 'original-plan', artifact_hash: hash }}
      actorId="independent-admin" setups={setups} disabled={false} onChoose={edit} />
    <label>Setup reference<input value={setups[0].commandId} onChange={(event) => edit('case:0', event.target.value)} /></label>
  </main>
}
function Surface() {
  const hash = params.get('setupPlanHash')
  if (hash) return <SetupSurface hash={hash} />
  return <main className="test-design-scope">
    <h1>Original fixture history browser contract</h1>
    <p>Production Runs section with intercepted archive ports. Not real authentication, full route navigation, PG, Temporal, exweb or business coverage.</p>
    <RunsSection context={{ projectId: 'p' }} />
  </main>
}
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}><I18nProvider><Surface /></I18nProvider></QueryClientProvider></StrictMode>)

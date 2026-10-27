import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { savedBuildAgentApi } from '../../../../../domains/system-image/savedBuildAgentApi'
import type { BuildPlan } from '../../../../../domains/system-image/types/buildPlan'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { ApiRequestError } from '../../../../../shared/api/client'

export function SavedBuildAgentAction({ scope, plan }: { scope: ImageReadScope; plan: BuildPlan }) {
  const user = useAuthUser()
  return user.data ? <SavedBuildEntry key={JSON.stringify([user.data.id, scope.sessionId, plan.plan_id, plan.plan_digest])}
    scope={scope} plan={plan} actorId={user.data.id} /> : null
}

function SavedBuildEntry({ scope, plan, actorId }: { scope: ImageReadScope; plan: BuildPlan; actorId: string }) {
  const { t } = useI18n()
  const storageKey = `nasus.saved-build-entry:${JSON.stringify([actorId, scope.projectId, plan.plan_id, plan.plan_digest])}`
  const [pendingConversation, setPendingConversation] = useState(() => {
    try { return sessionStorage.getItem(storageKey) ?? '' } catch { return '' }
  })
  const [goalId, setGoalId] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const inFlight = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  async function act() {
    if (inFlight.current || goalId) return
    inFlight.current = true
    setBusy(true)
    setFailed(false)
    try {
      const goal = pendingConversation
        ? await savedBuildAgentApi.recover(plan, pendingConversation, new AbortController().signal)
        : await start()
      setGoalId(goal.id)
      // Keep the read-only recovery marker across refresh, including successful starts.
    } catch (error) {
      setFailed(true)
      if (error instanceof ApiRequestError && [401, 403, 404, 502].includes(error.status)) scope.onFailure(true)
    }
    finally { inFlight.current = false; setBusy(false) }
  }
  async function start() {
    const conversation = await savedBuildAgentApi.conversation(plan)
    if (!mounted.current) throw new Error('Saved build entry is no longer visible')
    sessionStorage.setItem(storageKey, conversation.id)
    setPendingConversation(conversation.id)
    return savedBuildAgentApi.start(plan, conversation.id)
  }
  if (plan.proposal.policy_version !== 'nasus.image-investigation-plan.v3' || plan.project_id !== scope.projectId) return null
  return <details data-testid="saved-build-agent-entry">
    <summary>{t('Build with the agent')}</summary>
    <div className="build-plan-form structure-build-action">
      <p>{t('Use this saved plan, its original sources and target. Review the structural budget in the project before execution.')}</p>
      <p>{t('Model calls, repository execution and image publication are not authorized by this action.')}</p>
      {failed && <p role="alert">{t('The start outcome could not be verified. Read the existing conversation; no automatic retry was sent.')}</p>}
      {goalId ? <>
        <p role="status">{t('Saved-plan agent goal is available. Execution still requires separate confirmation.')}</p>
        <Link to={`/projects/${encodeURIComponent(scope.projectId)}`}>{t('Review execution confirmation')}</Link>
      </> : <button type="button" disabled={busy} onClick={() => void act()}>
        {t(busy ? 'Checking saved-plan goal...' : pendingConversation ? 'Read existing build goal' : 'Start from this saved plan')}
      </button>}
      <details><summary>{t('Equivalent chat command')}</summary><code>{`start build_plan:${plan.plan_id} digest:${plan.plan_digest}`}</code></details>
    </div>
  </details>
}

import { useSearchParams } from 'react-router-dom'
import { parseBuildReviewSelection } from '../../../../../domains/system-image/buildReviewHandoff'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { BuildReviewInspector } from './BuildReviewInspector'

export function BuildReviewNavigation({ projectId }: { projectId: string }) {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  let selection: ReturnType<typeof parseBuildReviewSelection> = null
  try { selection = parseBuildReviewSelection(params) } catch {
    return <p role="alert">{t('The build review link is invalid. No candidate was selected.')}</p>
  }
  if (!selection) return null
  const close = () => {
    const next = new URLSearchParams(params)
    next.delete('build_review_goal'); next.delete('build_review_invocation')
    next.delete('build_completion_request'); next.delete('build_completion_invocation')
    next.delete('build_owned_completion_request'); next.delete('build_owned_completion_invocation')
    next.delete('build_gap_assignment_request'); next.delete('build_gap_assignment_invocation')
    setParams(next, { replace: true })
  }
  return <BuildReviewInspector key={`${projectId}:${selection.goalId}:${selection.invocationId}`}
    projectId={projectId} selection={selection} close={close} />
}

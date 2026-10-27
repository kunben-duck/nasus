import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { platformApi } from '../platform/api'
import { semanticEvaluationApi } from './semanticEvaluationApi'
import type { LinkCandidatePage } from './linkCandidateApi'
import type { SemanticHistoryItem } from './types/semanticEvaluation'
import type { ImageReadScope } from './useImageRevisions'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useSemanticEvaluation(scope: ImageReadScope, page: LinkCandidatePage, recallLimit: number, recallInvocationId: string) {
  const client = useQueryClient()
  const [subjects, setSubjects] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [cursors, setCursors] = useState([''])
  const [selected, setSelected] = useState<Pick<SemanticHistoryItem, 'invocation_id' | 'request' | 'artifact_hash'> | null>(null)
  const submitted = useRef(false)
  const models = useQuery({ ...sensitive, queryKey: ['semantic-model-options', scope.sessionId],
    queryFn: ({ signal }) => platformApi.getModelConfigurations('chat', signal) })
  const choices = !models.isError && !models.isFetching ? models.data?.configurations.filter((config) =>
    config.route === 'chat' && !config.legacy_imported && config.last_test_result.ok === true && !!config.last_test_signature) ?? [] : []
  const preview = useMutation({ mutationFn: () => semanticEvaluationApi.preview({
    project_id: scope.projectId, image_revision_id: page.image_revision_id, expected_image_hash: page.image_artifact_hash,
    target_object_id: page.target.object_id, relation: page.relation, subject_object_ids: [...subjects].sort(), model_config_id: model, recall_limit: recallLimit,
    recall_invocation_id: recallInvocationId,
  }), retry: false })
  const execution = useMutation({ mutationFn: (prepared: NonNullable<typeof preview.data>) => semanticEvaluationApi.execute(prepared.preview, prepared.attemptKey),
    retry: false, onSuccess: (id, prepared) => setSelected({ invocation_id: id, request: prepared.preview.request, artifact_hash: null }),
    onSettled: () => client.invalidateQueries({ queryKey: ['semantic-history', scope.projectId, scope.sessionId] }),
  })
  const history = useQuery({ ...sensitive,
    queryKey: ['semantic-history', scope.projectId, scope.sessionId, page.image_revision_id, page.target.revision_id, page.relation, cursors.at(-1)],
    queryFn: ({ signal }) => semanticEvaluationApi.history(page, cursors.at(-1)!, signal) })
  const result = useQuery({ ...sensitive, queryKey: ['semantic-result', scope.projectId, scope.sessionId, selected],
    enabled: !!selected, queryFn: ({ signal }) => semanticEvaluationApi.result(page, selected!, signal) })
  const { onFailure } = scope
  useEffect(() => { if (history.isError || result.isError) onFailure(true) }, [history.isError, result.isError, onFailure])
  const busy = preview.isPending || execution.isPending
  const reviewBlocked = preview.data?.preview.review_screening.some((item) =>
    ['rejected_same_revisions', 'identity_unresolved', 'different_endpoints'].includes(item.status)) ?? false
  function reset() { preview.reset(); execution.reset(); setConfirmed(false); submitted.current = false }
  return { models, choices, model, subjects, confirmed, setConfirmed, preview, execution, history, result, selected, busy, reviewBlocked,
    chooseModel: (id: string) => { if (!busy) { setModel(id); reset() } },
    toggle: (id: string) => { if (!busy) { setSubjects((ids) => ids.includes(id) ? ids.filter((s) => s !== id) : ids.length < 30 ? [...ids, id] : ids); reset() } },
    prepare: () => { if (!busy && subjects.length && choices.some((c) => c.config_id === model)) { reset(); preview.mutate() } },
    execute: () => {
      if (busy || reviewBlocked || submitted.current || !confirmed || !preview.data || preview.isError || !choices.some((c) => c.config_id === model)) return
      submitted.current = true; setConfirmed(false); execution.mutate(preview.data)
    },
    inspect: (item: SemanticHistoryItem) => { if (!busy && item.state === 'archived') setSelected(item) },
    historyPage: cursors.length,
    previous: cursors.length > 1 ? () => setCursors(cursors.slice(0, -1)) : undefined,
    next: history.data?.next_after_id ? () => setCursors([...cursors, history.data!.next_after_id!]) : undefined,
    refreshHistory: () => { setCursors(['']); void client.invalidateQueries({ queryKey: ['semantic-history', scope.projectId, scope.sessionId] }) },
  }
}
export type SemanticEvaluationController = ReturnType<typeof useSemanticEvaluation>

import { useMutation } from '@tanstack/react-query'

import type { AgentGoal } from '../../domains/agent/types'
import { uploadSystemImageSourceFiles } from '../../domains/system-image/sourceUploadCommands'
import type { SystemImageData } from '../../domains/system-image/types'
import type { AgentMode } from './ProjectWorkspaceTypes'
import type { SourceBindingValues } from './components/sourceBindingDefaults'
import type { SourceBindingKey } from './components/sourceBindingCards'
import { useSourceBindingDrafts } from './components/useSourceBindingDrafts'
import { shouldShowSourceBindingPanel } from './projectWorkspaceSelectors'

export function useProjectWorkspaceSourceBindings({
  projectId,
  systemImage,
  mode,
  pendingGoal,
  disabled,
  buildSystemImageFromSources,
}: {
  projectId: string
  systemImage?: SystemImageData
  mode: AgentMode
  pendingGoal?: AgentGoal
  disabled: boolean
  buildSystemImageFromSources: (sources: SourceBindingValues) => void
}) {
  const sourceBindingDrafts = useSourceBindingDrafts(projectId, systemImage)
  const uploadMutation = useMutation({
    mutationFn: ({ key, files }: { key: SourceBindingKey; files: File[] }) => {
      if (key === 'code') {
        throw new Error('Code repositories must be connected with a Git URL or an approved server path.')
      }
      return uploadSystemImageSourceFiles(
        projectId,
        key === 'usDoc' ? 'us_doc' : 'test_asset',
        files,
      )
    },
    onSuccess: (result, variables) => {
      sourceBindingDrafts.updateSourceBinding(variables.key, result.source_uri)
    },
  })

  function submitSourceBindings() {
    if (disabled) return
    sourceBindingDrafts.submitSourceBindings(buildSystemImageFromSources)
  }

  function uploadSourceFiles(key: SourceBindingKey, files: File[]) {
    if (files.length === 0) return
    uploadMutation.mutate({ key, files })
  }

  function updateSourceBinding(key: SourceBindingKey, value: string) {
    uploadMutation.reset()
    sourceBindingDrafts.updateSourceBinding(key, value)
  }

  return {
    shouldShowPanel: shouldShowSourceBindingPanel(mode, systemImage, pendingGoal),
    values: sourceBindingDrafts.values,
    visibleError:
      uploadMutation.error instanceof Error
        ? uploadMutation.error.message
        : sourceBindingDrafts.visibleError,
    updateSourceBinding,
    uploadSourceFiles,
    uploadingSourceKey: uploadMutation.isPending ? uploadMutation.variables?.key : undefined,
    submitSourceBindings,
  }
}

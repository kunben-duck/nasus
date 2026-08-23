import { useState } from 'react'

import type { SystemImageData } from '../../../domains/system-image/types'
import { sourceBindingDefaults, type SourceBindingValues } from './sourceBindingDefaults'

export function useSourceBindingDrafts(projectId: string, systemImage?: SystemImageData) {
  const [drafts, setDrafts] = useState<Record<string, SourceBindingValues>>({})
  const [error, setError] = useState<{ projectId: string; message: string } | null>(null)
  const values = drafts[projectId] ?? sourceBindingDefaults(systemImage)
  const visibleError = error?.projectId === projectId ? error.message : null

  function updateSourceBinding(key: keyof SourceBindingValues, value: string) {
    setDrafts((current) => ({
      ...current,
      [projectId]: {
        ...(current[projectId] ?? sourceBindingDefaults(systemImage)),
        [key]: value,
      },
    }))
    setError(null)
  }

  function submitSourceBindings(onSubmit: (values: SourceBindingValues) => void) {
    if (!values.code.trim()) {
      setError({
        projectId,
        message: 'Provide a code repository before building the system image. US documents and test assets are optional.',
      })
      return
    }
    onSubmit(values)
  }

  return {
    values,
    visibleError,
    updateSourceBinding,
    submitSourceBindings,
  }
}

import { buildStudioActionCommand } from './studioActionCommand'
import type { StudioSourceBindingValues, ToolActionCommand } from './types'

export function buildSystemImageSourceActionPlan(
  projectId: string,
  sources: StudioSourceBindingValues,
): ToolActionCommand[] {
  const source_specs = [
    { source_type: 'code', source_uri: sources.code.trim(), label: 'Code repository' },
    { source_type: 'us_doc', source_uri: sources.usDoc.trim(), label: 'Historical US documents' },
    { source_type: 'test_asset', source_uri: sources.testAsset.trim(), label: 'Historical test assets' },
  ].filter((source) => source.source_uri)

  return [
    buildStudioActionCommand('system-image.register-sources', {
      projectId,
      input: { source_specs },
    }) as ToolActionCommand,
    buildStudioActionCommand('system-image.ingest-sources', { projectId }) as ToolActionCommand,
    buildStudioActionCommand('system-image.materialize-context', { projectId }) as ToolActionCommand,
    buildStudioActionCommand('system-image.initialize-baseline', { projectId }) as ToolActionCommand,
  ]
}

export function buildSystemImageSourceBindingMessage(sources: StudioSourceBindingValues): string {
  return [
    `code path ${sources.code.trim()}`,
    sources.usDoc.trim() ? `US docs URI ${sources.usDoc.trim()}` : '',
    sources.testAsset.trim() ? `test assets URI ${sources.testAsset.trim()}` : '',
  ].filter(Boolean).join(', ')
}

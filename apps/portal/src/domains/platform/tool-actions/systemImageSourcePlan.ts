import { buildStudioActionCommand } from './studioActionCommand'
import type { StudioSourceBindingValues, ToolActionCommand } from './types'
import type { Locale } from '../../../shared/i18n/I18nProvider'

export function buildSystemImageSourceActionPlan(
  projectId: string,
  sources: StudioSourceBindingValues,
): ToolActionCommand[] {
  const source_specs = [
    { source_type: 'code', source_uri: sources.code.trim(), label: 'Code repository',
      ...(sources.codeRef?.trim() ? { tracked_ref: sources.codeRef.trim() } : {}) },
    { source_type: 'us_doc', source_uri: sources.usDoc.trim(), label: 'Historical US documents' },
    { source_type: 'test_asset', source_uri: sources.testAsset.trim(), label: 'Historical test assets' },
  ].filter((source) => source.source_uri)

  return [
    buildStudioActionCommand('system-image.register-sources', {
      projectId,
      input: { source_specs },
    }) as ToolActionCommand,
    buildStudioActionCommand('system-image.ingest-sources', { projectId }) as ToolActionCommand,
  ]
}

export function buildSystemImageSourceBindingMessage(
  sources: StudioSourceBindingValues,
  locale: Locale = 'en',
): string {
  if (locale === 'zh') {
    return [
      `代码路径 ${sources.code.trim()}`,
      sources.codeRef?.trim() ? `tracked_ref=${sources.codeRef.trim()}` : '',
      sources.usDoc.trim() ? `US 文档地址 ${sources.usDoc.trim()}` : '',
      sources.testAsset.trim() ? `测试资产地址 ${sources.testAsset.trim()}` : '',
    ].filter(Boolean).join('，')
  }
  return [
    `code path ${sources.code.trim()}`,
    sources.codeRef?.trim() ? `tracked_ref=${sources.codeRef.trim()}` : '',
    sources.usDoc.trim() ? `US docs URI ${sources.usDoc.trim()}` : '',
    sources.testAsset.trim() ? `test assets URI ${sources.testAsset.trim()}` : '',
  ].filter(Boolean).join(', ')
}

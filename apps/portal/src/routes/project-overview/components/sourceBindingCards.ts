import type { SystemImageData } from '../../../domains/system-image/types'
import type { SourceBindingValues } from './sourceBindingDefaults'

export type SourceBindingKey = keyof SourceBindingValues
export type SourceBindingSource = SystemImageData['sources'][number]

export type SourceBindingCardConfig = {
  key: SourceBindingKey
  sourceType: SourceBindingSource['source_type']
  icon: string
  label: string
  detail: string
  placeholder: string
  testId: string
  required: boolean
}

export const sourceBindingCards: SourceBindingCardConfig[] = [
  {
    key: 'code',
    sourceType: 'code',
    icon: 'account_tree',
    label: 'Code repository',
    detail: 'Local path or Git URL used for code symbols, modules, and changed-area context.',
    placeholder: '/absolute/path/to/repo or https://git.example/repo.git',
    testId: 'source-code-input',
    required: true,
  },
  {
    key: 'usDoc',
    sourceType: 'us_doc',
    icon: 'description',
    label: 'US documents',
    detail: 'Historical and current user stories, acceptance criteria, and product notes.',
    placeholder: 'Upload files or provide a managed source URI',
    testId: 'source-us-input',
    required: false,
  },
  {
    key: 'testAsset',
    sourceType: 'test_asset',
    icon: 'fact_check',
    label: 'Test assets',
    detail: 'Historical test cases, automation scripts, and reusable evidence packs.',
    placeholder: 'Upload files or provide a managed source URI',
    testId: 'source-tests-input',
    required: false,
  },
]

export function sourceMapByType(systemImage?: SystemImageData) {
  return new Map((systemImage?.sources ?? []).map((source) => [source.source_type, source]))
}

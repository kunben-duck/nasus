import type { CodeFileAnalysis, CodeStructureFact, ParserStatus, StructureKind } from './types/codeAnalysis'

export const parserLabels: Record<ParserStatus, string> = {
  parsed: 'Parsed', unsupported: 'Unsupported', failed: 'Failed', not_analyzed: 'Not analyzed',
}
export const structureLabels: Record<StructureKind, string> = {
  module: 'File modules', package: 'Package declarations', service: 'Service declarations', entrypoint: 'Application entries',
  route: 'Routes', event_consumer: 'Event listeners', database_access: 'Database boundaries',
  test_entrypoint: 'Test entries', configuration_boundary: 'Configuration candidates',
}
export const observationLabels = { observed: 'Static observation', unresolved: 'Needs resolution', path_hint: 'Filename hint' }
export const identityLabels = { exact: 'Symbol matched', ambiguous: 'Ambiguous identity', unresolved: 'Unresolved identity' }
export const relationLabels = {
  belongs_to: 'Reported containment', depends_on: 'Reported dependency', calls: 'Reported call', exposes: 'Reported exposure',
}
export const analysisSectionLabels = { files: 'Files', facts: 'Structure', entities: 'Received entities', relationships: 'Received relations' }
const reasons: Record<string, string> = {
  syntax_valid: 'Syntax parsed; semantic correctness is not established.',
  syntax_error: 'Syntax errors prevented registration.', parser_failed: 'The parser could not analyze this file.',
  non_utf8_source: 'Lossless UTF-8 decoding is unavailable.', grammar_unavailable: 'No supported grammar for this file type.',
  text_not_extracted: 'No text was extracted from this archived file.', provider_not_reported: 'The provider did not report parser coverage.',
}
export function analysisReason(file: CodeFileAnalysis) { return reasons[file.reason] ?? file.reason }
export function factLocation(fact: CodeStructureFact) { return `${fact.relative_path}:${fact.start_line}-${fact.end_line}` }

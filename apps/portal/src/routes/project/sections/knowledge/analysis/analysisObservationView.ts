import { analysisReason, factLocation, identityLabels, observationLabels, parserLabels, relationLabels, structureLabels } from '../../../../../domains/system-image/codeAnalysisLabels'
import type { CodeAnalysisPage } from '../../../../../domains/system-image/types/codeAnalysis'

export interface AnalysisObservationView {
  key: string
  heading: string
  status: string
  badge: string
  description: string
  language?: string
  location?: string
  details: { label: string; value: string; translateValue?: boolean }[]
}

export function analysisObservationViews(items: CodeAnalysisPage['items']): AnalysisObservationView[] {
  return items.map((item, index) => {
    if ('provider_node_id' in item) return {
      key: `entity:${item.provider_node_id}`, heading: item.name, status: item.identity_status,
      badge: identityLabels[item.identity_status], language: item.language,
      description: 'Received entity observation. Identity matching does not imply admission to the system image.',
      location: `${item.relative_path}:${item.start_line}-${item.end_line}`,
      details: [{ label: 'Observation node ID', value: item.provider_node_id },
        { label: 'Qualified name', value: item.qualified_name }, { label: 'Entity kind', value: item.entity_kind },
        { label: 'Location precision', value: item.location_precision }],
    }
    if ('relationship_kind' in item) return {
      key: `relation:${item.from_provider_node_id}:${item.relationship_kind}:${item.to_provider_node_id}:${index}`,
      heading: relationLabels[item.relationship_kind], status: 'observed', badge: 'Static observation',
      description: 'Received relation observation. It does not prove business correctness or test coverage.',
      details: [{ label: 'From observation', value: item.from_provider_node_id },
        { label: 'To observation', value: item.to_provider_node_id },
        { label: 'Uncalibrated provider score', value: String(item.confidence) }],
    }
    const fact = 'kind' in item
    const details: AnalysisObservationView['details'] = fact
      ? [{ label: 'Rule', value: item.rule }, ...item.supporting_spans.flatMap((span) => [
        { label: span.role === 'controller' ? 'Controller declaration' : 'Class mapping',
          value: `${item.relative_path}:${span.start_line}-${span.end_line}` },
        { label: 'Snippet hash', value: span.snippet_hash },
      ])]
      : [{ label: 'Parser', value: item.parser_version },
        { label: 'Rules', value: item.rules.join(', ') || 'None reported', translateValue: !item.rules.length },
        { label: 'Syntax errors', value: `${item.syntax_errors}` }]
    details.push({ label: 'File hash', value: item.source_file_hash })
    if (fact && item.snippet_hash) details.push({ label: 'Snippet hash', value: item.snippet_hash })
    return {
      key: `${item.relative_path}:${index}`, heading: fact ? item.name : item.relative_path, status: item.status,
      badge: fact ? observationLabels[item.status] : parserLabels[item.status],
      description: fact ? structureLabels[item.kind] : analysisReason(item),
      language: fact ? undefined : item.language, location: fact ? factLocation(item) : undefined, details,
    }
  })
}

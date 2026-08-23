import type { DocumentationEntry } from '../../domains/platform/types'

function DocCard({ entry }: { entry: DocumentationEntry }) {
  return (
    <article className="doc-card">
      <span>{entry.category}</span>
      <h3>{entry.title}</h3>
      <p>{entry.copy}</p>
    </article>
  )
}

export function DocumentationContent({ entries }: { entries: DocumentationEntry[] }) {
  return (
    <section className="docs-page">
      <div className="page-heading compact">
        <span className="eyebrow">Documentation</span>
        <h1>How Nasus works</h1>
        <p>Product docs explain the three product modules, agent-first workflow, and quality closure concepts.</p>
      </div>
      <div className="doc-grid">
        {entries.map((entry) => <DocCard entry={entry} key={entry.id} />)}
      </div>
    </section>
  )
}

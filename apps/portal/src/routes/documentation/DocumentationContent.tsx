import type { DocumentationEntry } from '../../domains/platform/types'
import { useI18n } from '../../shared/i18n/I18nProvider'

function DocCard({ entry }: { entry: DocumentationEntry }) {
  const { tx } = useI18n()
  return (
    <article className="doc-card">
      <span>{tx(entry.category)}</span>
      <h3>{tx(entry.title)}</h3>
      <p>{tx(entry.copy)}</p>
    </article>
  )
}

export function DocumentationContent({ entries }: { entries: DocumentationEntry[] }) {
  const { t } = useI18n()
  return (
    <section className="docs-page">
      <div className="page-heading compact">
        <span className="eyebrow">{t('Documentation')}</span>
        <h1>{t('How Nasus works')}</h1>
        <p>{t('Product docs explain the three product modules, agent-first workflow, and quality closure concepts.')}</p>
      </div>
      <div className="doc-grid">
        {entries.map((entry) => <DocCard entry={entry} key={entry.id} />)}
      </div>
    </section>
  )
}

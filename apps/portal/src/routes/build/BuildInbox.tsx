import { useDeferredValue, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { useBuildInbox } from '../../domains/agent/useBuildInbox'
import { useDashboardContent } from '../../domains/platform/useTopLevelContent'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { BuildSidebarToggle } from './components/BuildSidebarToggle'
import './inbox.css'

const pageSize = 25
export function BuildInbox() {
  const { t, locale } = useI18n()
  const navigate = useNavigate()
  const [project, setProject] = useState(''), [term, setTerm] = useState(''), [page, setPage] = useState(0)
  const q = useDeferredValue(term.trim())
  const { dashboardQuery } = useDashboardContent()
  const projects = dashboardQuery.data?.projects ?? []
  const history = useBuildInbox(project, q, page, pageSize)
  return <TopLevelStudioShell active="build" statusDependencies={[dashboardQuery, history]}>
    {(sidebar) => <section className="build-inbox">
      <BuildSidebarToggle {...sidebar} />
      <header><h1>{t('My conversations')}</h1>
        <button className="tool-chip" type="button" onClick={() => navigate('/build?session=' + crypto.randomUUID())}>{t('New build conversation')}</button></header>
      <div className="inbox-filters"><input type="search" aria-label={t('Search conversations')} placeholder={t('Search conversations')} maxLength={200} value={term}
        onChange={e => { setTerm(e.target.value); setPage(0) }} />
        <select aria-label={t('Filter by project')} value={project} onChange={e => { setProject(e.target.value); setPage(0) }}>
          <option value="">{t('All projects')}</option><option value="unbound">{t('Unlinked project')}</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
      {history.isPending ? <p role="status">{t('Loading conversations…')}</p> : history.isError ?
        <p role="alert">{t('Could not load conversations.')} <button onClick={() => void history.refetch()}>{t('Retry')}</button></p> :
        history.data.items.length ? <ul>{history.data.items.map(item => <li key={item.id}>
          <Link to={'/build?conversation=' + encodeURIComponent(item.id)}>
            <span><strong>{item.title || t('Build')}</strong><small>{projects.find(p => p.id === item.project_id)?.name ?? item.project_id ?? t('Unlinked project')}</small></span>
            <span>{item.task_status && <b>{t(({ confirmation: 'Awaiting confirmation', paused: 'Task paused', running: 'Task running' } as const)[item.task_status])}</b>}
              {item.activity_at && <time dateTime={item.activity_at}>{new Date(item.activity_at).toLocaleString(locale)}</time>}</span>
          </Link></li>)}</ul> : <p>{term || project ? t('No matching conversations.') : t('No conversations yet. Start a new conversation to begin.')}</p>}
      <footer>{page > 0 && <button onClick={() => setPage(page - 1)}>{t('Previous page')}</button>}
        {history.data?.has_more && <button onClick={() => setPage(page + 1)}>{t('Next page')}</button>}</footer>
    </section>}
  </TopLevelStudioShell>
}

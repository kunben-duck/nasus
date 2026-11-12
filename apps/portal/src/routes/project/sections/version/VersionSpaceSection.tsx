import { Link, useSearchParams } from 'react-router-dom'
import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { useDeliveryIterations } from '../../../../domains/quality-loop/useVersionDelivery'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { DeliveryDetails } from './DeliveryDetails'

export function VersionSpaceSection({ context }: { context: ProjectRouteContext }) {
  const { t } = useI18n(), [params, setParams] = useSearchParams()
  const projectId = context.project.id, { query, versions } = useDeliveryIterations(projectId)
  const ids = params.getAll('version_id'), selectedId = ids.length === 1 ? ids[0] : ''
  const selected = versions?.find((item) => item.id === selectedId)
  return <>
    <div className="agent-heading"><h1>{t('Version Space')}</h1>
      <Link className="delivery-entry" to={`/projects/${encodeURIComponent(projectId)}/versions/create`}>{t('Create delivery iteration')}</Link></div>
    <section className="delivery-panel" aria-label={t('Delivery iterations')}>
      <div className="delivery-toolbar"><h2>{t('Delivery iterations')}</h2>
        <button type="button" className="small-btn" disabled={query.isFetching} onClick={() => void query.refetch()}>{t('Reload iterations')}</button></div>
      <p>{t('Choose an explicit iteration. Its baseline and evidence are isolated from other versions.')}</p>
      {query.isFetching && <p role="status">{t('Loading iterations...')}</p>}
      {query.isError && <p role="alert">{t('Iterations could not be verified. Reload to check access.')}</p>}
      {versions && <label>{t('Selected delivery iteration')}<select value={selected?.id ?? ''} onChange={(event) => {
        const next = new URLSearchParams(params)
        if (event.target.value) next.set('version_id', event.target.value)
        else next.delete('version_id')
        for (const key of ['publication_id', 'baseline_id', 'image_revision_id', 'image_artifact_hash']) next.delete(key)
        setParams(next)
      }}><option value="">{t('Select an iteration')}</option>
        {versions.map((version) => <option key={version.id} value={version.id}>{version.name} · {version.id}</option>)}
      </select></label>}
      {versions?.length === 0 && <p>{t('No delivery iterations yet.')}</p>}
      {versions && (ids.length > 1 || (selectedId && !selected)) && <p role="alert">{t('The selected iteration is not available in this project.')}</p>}
    </section>
    {selected && <DeliveryDetails key={`${projectId}:${selected.id}`} projectId={projectId} versionId={selected.id} />}
  </>
}

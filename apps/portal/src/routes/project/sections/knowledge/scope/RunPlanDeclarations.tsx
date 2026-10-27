import type { ScriptArchive } from '../../../../../domains/quality-loop/types/automationScripts'
import type { RunPlanFields } from '../../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'

export function RunPlanDeclarations({ draft, fields, edit, disabled }: {
  draft: ScriptArchive; fields: RunPlanFields; edit: (value: Partial<RunPlanFields>) => void; disabled: boolean
}) {
  const { t } = useI18n()
  const text = (name: keyof Omit<RunPlanFields, 'fixtures' | 'kind'>, label: string, limit = 128) => <label>{label}
    <input value={fields[name]} maxLength={limit} spellCheck={false} onChange={(event) => edit({ [name]: event.target.value })} /></label>
  return <fieldset disabled={disabled}><legend>{t('Target input declarations')}</legend>
    <p>{t('Declare the exact target artifacts, environment and data. No URL, setup description or cleanup description is executed by this form.')}</p>
    <div className="scope-grid">
      {text('artifactName', t('Build artifact name'))}{text('artifactHash', t('Build artifact SHA-256'), 71)}
      {text('definitionHash', t('Build definition SHA-256'), 71)}{text('runtime', t('Target runtime'))}
      {text('runtimeVersion', t('Runtime version'))}{text('buildTool', t('Build tool'))}{text('buildToolVersion', t('Build tool version'))}
      {text('environmentId', t('Target environment ID'))}
      <label>{t('Target environment kind')}<select value={fields.kind} onChange={(event) => edit({ kind: event.target.value as RunPlanFields['kind'] })}>
        <option value="local">{t('Local')}</option><option value="test">{t('Test environment')}</option><option value="staging">{t('Staging')}</option></select></label>
      {text('origin', t('Target HTTP origin'), 2048)}{text('inventoryHash', t('Environment inventory SHA-256'), 71)}
    </div>
    <ScopeText label={t('Environment isolation declaration')} value={fields.isolation} onChange={(isolation) => edit({ isolation })} />
    {draft.result.prepared.cases.map((item) => { const fixture = fields.fixtures[item.case_id]
      const change = (value: Partial<typeof fixture>) => edit({ fixtures: { ...fields.fixtures, [item.case_id]: { ...fixture, ...value } } })
      return <details className="scope-record" key={item.case_id}><summary>{item.title}</summary><code>{item.case_id}</code>
        <strong>{t('Original case preconditions')}</strong><ul>{item.preconditions.map((value, index) => <li key={index}>{value}</li>)}</ul>
        <label>{t('Fixture manifest SHA-256')}<input maxLength={71} value={fixture.dataHash} spellCheck={false} onChange={(event) => change({ dataHash: event.target.value })} /></label>
        <ScopeText label={t('Fixture setup declarations, one per line')} value={fixture.setup} onChange={(setup) => change({ setup })} />
        <ScopeText label={t('Fixture cleanup declarations, one per line')} value={fixture.cleanup} onChange={(cleanup) => change({ cleanup })} />
      </details>
    })}
    <ScopeText label={t('Execution plan preparation reason')} value={fields.reason} onChange={(reason) => edit({ reason })} />
  </fieldset>
}

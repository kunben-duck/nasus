import type { ScriptArchive } from '../../../../../domains/quality-loop/types/automationScripts'
import type { RunPlanFields } from '../../../../../domains/quality-loop/types/runPlans'
import type { TargetEnvironmentOptions } from '../../../../../domains/quality-loop/targetEnvironments'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'

export function RunPlanDeclarations({ draft, fields, edit, disabled, environments }: {
  draft: ScriptArchive; fields: RunPlanFields; edit: (value: Partial<RunPlanFields>) => void; disabled: boolean; environments?: TargetEnvironmentOptions
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
      <label>{t('Registered target environment')}<select value={fields.environmentId} disabled={!environments} onChange={(event) => {
        const selected = environments?.options.find((item) => item.environment_id === event.target.value)
        edit({ environmentId: selected?.environment_id ?? '', kind: 'local', origin: selected?.base_url ?? '', inventoryHash: selected?.inventory_hash ?? '' })
      }}><option value="">{t('Select an isolated environment')}</option>
        {environments?.options.map((item) => <option key={item.environment_id} value={item.environment_id}>{item.environment_id} · {item.profile}</option>)}
      </select></label>
      {fields.environmentId && <p>{t('Registry selection is not health verification or permission to execute.')}<code>{fields.origin}</code><code>{fields.inventoryHash}</code></p>}
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

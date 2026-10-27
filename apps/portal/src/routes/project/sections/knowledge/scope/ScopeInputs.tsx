import { oracleKeys, type ObservableOracle } from '../../../../../domains/quality-loop/types/observableOracle'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function ScopeText({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="scope-text">{label}<textarea rows={2} maxLength={2000} value={value} onChange={(event) => onChange(event.target.value)} /></label>
}
export function ScopeOracle({ title, value, onChange }: { title: string; value: ObservableOracle; onChange: (value: ObservableOracle) => void }) {
  const { t } = useI18n()
  const labels = { preconditions: t('Oracle preconditions'), action: t('Action under test'), observation: t('Observable output'), expected_result: t('Required result') }
  return <fieldset className="scope-oracle"><legend>{title}</legend><div className="scope-grid">{oracleKeys.map((key) =>
    <ScopeText key={key} label={labels[key]} value={value[key]} onChange={(text) => onChange({ ...value, [key]: text })} />)}</div></fieldset>
}
export function ScopeReferences({ title, options, value, onChange }: {
  title: string; options: { id: string; text: string }[]; value: string[]; onChange: (value: string[]) => void
}) {
  return <fieldset className="scope-references"><legend>{title}</legend>{options.map((option) => <label key={option.id}>
    <input type="checkbox" checked={value.includes(option.id)} onChange={(event) => onChange(event.target.checked ? [...value, option.id] : value.filter((id) => id !== option.id))} />
    <span>{option.text}<code>{option.id}</code></span></label>)}</fieldset>
}

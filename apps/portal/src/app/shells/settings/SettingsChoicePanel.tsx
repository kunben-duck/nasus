import type { SettingsChoice } from './settingsTypes'

export function SettingsChoicePanel<T extends string>({
  value,
  disabled,
  choices,
  onChange,
}: {
  value?: T
  disabled: boolean
  choices: SettingsChoice<T>[]
  onChange: (value: T) => void
}) {
  return (
    <div className="settings-submenu settings-submenu-compact">
      {choices.map((choice) => (
        <button
          className={value === choice.value ? 'selected' : ''}
          disabled={disabled}
          key={choice.value}
          onClick={() => onChange(choice.value)}
          type="button"
        >
          <span>{value === choice.value ? '●' : '○'}</span>
          <span>{choice.label}</span>
        </button>
      ))}
    </div>
  )
}

import { useI18n } from '../../i18n/I18nProvider'

export function BuildPromptInput({
  prompt,
  setPrompt,
  runPrompt,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
}) {
  const { t } = useI18n()
  return (
    <textarea
      data-testid="build-agent-input"
      value={prompt}
      onChange={(event) => setPrompt(event.target.value)}
      placeholder={t('Describe a quality project and let Nasus do the rest')}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          runPrompt()
        }
      }}
    />
  )
}

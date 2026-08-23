export function BuildPromptInput({
  prompt,
  setPrompt,
  runPrompt,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
}) {
  return (
    <textarea
      data-testid="build-agent-input"
      value={prompt}
      onChange={(event) => setPrompt(event.target.value)}
      placeholder="Describe a quality project and let Nasus do the rest"
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          runPrompt()
        }
      }}
    />
  )
}

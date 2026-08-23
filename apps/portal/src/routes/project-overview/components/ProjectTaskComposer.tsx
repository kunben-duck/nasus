import type { StudioActionId } from '../../../domains/platform/tool-actions'

export function ProjectTaskComposer({
  prompt,
  setPrompt,
  runPrompt,
  initializeSystemImage,
  invokeProjectAction,
  disabled,
  actionControlsDisabled,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  initializeSystemImage: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
  disabled: boolean
  actionControlsDisabled: boolean
}) {
  return (
    <div className="task-composer">
      <textarea
        data-testid="project-agent-input"
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder="Start typing a prompt to see what our agents can do"
        disabled={disabled}
      />
      <div className="task-chip-row">
        <button className="tool-chip" disabled={actionControlsDisabled}>Tools</button>
        <button className="tool-chip active" data-testid="tool-system-image" onClick={initializeSystemImage} disabled={actionControlsDisabled}>System image ×</button>
        <button className="tool-chip active" onClick={() => invokeProjectAction('quality-loop.continue-goal')} disabled={actionControlsDisabled}>Quality loop ×</button>
        <button className="tool-chip" data-testid="tool-release-gate" onClick={() => invokeProjectAction('release.assess')} disabled={actionControlsDisabled}>Release gate</button>
        <button className="round-icon" data-testid="project-agent-submit" onClick={runPrompt} disabled={disabled}>↵</button>
      </div>
    </div>
  )
}

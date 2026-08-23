import type { ProjectRouteContext } from '../../ProjectRouteTypes'

export function VersionCreateSection({ context }: { context: ProjectRouteContext }) {
  return (
    <>
      <div className="agent-heading">
        <h1>Create Version Branch</h1>
        <div className="segmented">
          <button className="active">Summary</button>
          <button>Owners</button>
          <button>Fork</button>
        </div>
      </div>
      <div className="source-binding-panel">
        <div className="source-binding-header">
          <div>
            <span className="eyebrow">Version tool</span>
            <strong>Use the agent to create a governed version branch</strong>
            <p>
              Version creation remains a tool-backed write action. The first formal implementation should invoke
              version tools through ToolInvocationRuntime rather than mutating project state in the page.
            </p>
          </div>
          <span className="source-status-pill pending">tool-first</span>
        </div>
        <div className="task-composer">
          <textarea
            data-testid="version-create-agent-input"
            value={context.prompt}
            onChange={(event) => context.setPrompt(event.target.value)}
            placeholder={`Create a new version branch for ${context.project.name}`}
            disabled={context.loading}
          />
          <div className="task-chip-row">
            <button className="tool-chip active" disabled={context.loading}>
              Version branch ×
            </button>
            <button className="round-icon" onClick={context.runPrompt} disabled={context.loading}>
              ↵
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

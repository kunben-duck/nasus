import type { AgentMode } from '../ProjectWorkspaceTypes'

export function AgentModeTabs({
  mode,
  setMode,
}: {
  mode: AgentMode
  setMode: (mode: AgentMode) => void
}) {
  return (
    <div className="agent-heading">
      <h1>Build with Agents</h1>
      <div className="segmented">
        <button className={mode === 'planning' ? 'active' : ''} onClick={() => setMode('planning')}>Agents</button>
        <button className={mode === 'sources' ? 'active' : ''} onClick={() => setMode('sources')}>Sources</button>
        <button className={mode === 'quality' ? 'active' : ''} onClick={() => setMode('quality')}>Quality</button>
      </div>
    </div>
  )
}

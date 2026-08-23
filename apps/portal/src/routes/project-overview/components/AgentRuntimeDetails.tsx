import type { AgentGoal, AgentMemoryContextView, AgentSwarmRun } from '../../../domains/agent/types'
import { MemoryContextPanel } from './MemoryContextPanel'
import { SwarmRunPanel } from './SwarmRunPanel'
import { ThinkingCard } from './ThinkingCard'

export function AgentRuntimeDetails({
  goal,
  memoryContext,
  swarmRuns,
}: {
  goal?: AgentGoal
  memoryContext?: AgentMemoryContextView
  swarmRuns: AgentSwarmRun[]
}) {
  if (!goal && !memoryContext && !swarmRuns.length) return null

  return (
    <section className="agent-runtime-details" data-testid="agent-runtime-details">
      <ThinkingCard goal={goal} />
      <MemoryContextPanel context={memoryContext} />
      <SwarmRunPanel swarms={swarmRuns} />
    </section>
  )
}

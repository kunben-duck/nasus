import { GlobalPageFrame } from '../app/PageFrames'
import { documentationInspectorRail } from '../app/inspectorRails'
import { ConversationWorkspaceCard } from '../components/ConversationWorkspaceCard'
import { Surface } from '../components/WorkspaceShell'
import { useConversation } from '../hooks/useConversation'
import { useQuery } from '@tanstack/react-query'
import { api } from '../features/api'

export function DocumentationPage({
  title = 'Documentation',
  description = 'The documentation area stays first-class in the product shell so onboarding, branching, governance, and asset-pack concepts are always reachable.',
}: {
  title?: string
  description?: string
}) {
  const { conversation, sendMessage } = useConversation('documentation', 'documentation', title)
  const documentationQuery = useQuery({
    queryKey: ['documentation'],
    queryFn: api.getDocumentation,
  })

  return (
    <GlobalPageFrame rail={documentationInspectorRail(documentationQuery.data)}>
      <Surface title={title} description={description}>
        <div className="section-grid two-up">
          <ConversationWorkspaceCard
            title="Documentation conversation"
            placeholder="Ask how Nasus works, how branching behaves, or how a workflow closes"
            suggestions={[
              'Explain the system image branching model',
              'How does an approval and merge flow work?',
            ]}
            messages={conversation?.messages ?? []}
            agentGoals={conversation?.agent_goals ?? []}
            onSubmit={sendMessage}
            compact
          />
          <article className="panel-card">
            <p className="eyebrow">Core topics</p>
            <ul className="simple-list">
              <li>System image branching</li>
              <li>Quality asset packs</li>
              <li>Agent-first tool invocation</li>
              <li>Approval and merge flows</li>
            </ul>
          </article>
          <article className="panel-card">
            <p className="eyebrow">Current implementation note</p>
            <p className="surface-description">This route is intentionally live from day one so the product shell matches the agreed IA even before the full docs UI is built.</p>
          </article>
        </div>
      </Surface>
    </GlobalPageFrame>
  )
}

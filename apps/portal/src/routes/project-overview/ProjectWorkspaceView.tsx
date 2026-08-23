import { AgentCardGrid } from './components/AgentCardGrid'
import { AgentGoalPanel } from './components/AgentGoalPanel'
import { AgentRuntimeDetails } from './components/AgentRuntimeDetails'
import { AgentLog } from './components/AgentLog'
import { AgentModeTabs } from './components/AgentModeTabs'
import { ConfirmationGates } from './components/ConfirmationGates'
import { ProjectTaskComposer } from './components/ProjectTaskComposer'
import { QualityAssetPanel } from './components/QualityAssetPanel'
import { SourceBindingPanel } from './components/SourceBindingPanel'
import { SystemImageStrip } from './components/SystemImageStrip'
import { ToolInvocationRail } from './components/ToolInvocationRail'
import { createProjectWorkspaceCardActions } from './projectWorkspaceCardActions'
import { qualityAssetPanelModel, selectPendingBaselineInvocation } from './projectWorkspaceSelectors'
import type { ProjectWorkspaceViewProps } from './ProjectWorkspaceViewTypes'
import { useProjectWorkspaceSourceBindings } from './useProjectWorkspaceSourceBindings'
import { WorkspaceToolbar } from './components/WorkspaceToolbar'

export function ProjectWorkspaceView({
  project,
  workspace,
  systemImage,
  mode,
  setMode,
  messages,
  agentGoal,
  agentGoalExplanation,
  memoryContext,
  swarmRuns,
  toolInvocations,
  pendingGoal,
  prompt,
  setPrompt,
  runPrompt,
  invokeProjectAction,
  confirmPendingGoal,
  initializeSystemImage,
  buildSystemImageFromSources,
  confirmToolInvocation,
  loading,
  activeActionId,
  sidebarCollapsed,
  toggleSidebar,
}: ProjectWorkspaceViewProps) {
  const actionControlsDisabled = Boolean(activeActionId)
  const composerDisabled = loading || actionControlsDisabled
  const pendingBaselineInvocation = selectPendingBaselineInvocation(toolInvocations, pendingGoal)
  const cardActions = createProjectWorkspaceCardActions({ setMode, initializeSystemImage, invokeProjectAction })
  const sourceBindings = useProjectWorkspaceSourceBindings({
    projectId: project.id,
    systemImage,
    mode,
    pendingGoal,
    disabled: composerDisabled,
    buildSystemImageFromSources,
  })

  return (
    <section className="agent-workspace" data-testid="agent-workspace">
      <WorkspaceToolbar title={project.name} sidebarCollapsed={sidebarCollapsed} toggleSidebar={toggleSidebar} />
      <AgentModeTabs mode={mode} setMode={setMode} />
      <AgentCardGrid disabled={actionControlsDisabled} onCardAction={(title) => cardActions[title]()} />
      <SystemImageStrip systemImage={systemImage} project={project} />
      {sourceBindings.shouldShowPanel ? (
        <SourceBindingPanel
          systemImage={systemImage}
          values={sourceBindings.values}
          error={sourceBindings.visibleError}
          loading={loading}
          onChange={sourceBindings.updateSourceBinding}
          onUpload={sourceBindings.uploadSourceFiles}
          uploadingSourceKey={sourceBindings.uploadingSourceKey}
          onSubmit={sourceBindings.submitSourceBindings}
        />
      ) : null}
      <AgentGoalPanel goal={agentGoal} explanation={agentGoalExplanation} />
      <AgentRuntimeDetails goal={agentGoal} memoryContext={memoryContext} swarmRuns={swarmRuns} />
      <ToolInvocationRail invocations={toolInvocations} />
      <QualityAssetPanel model={qualityAssetPanelModel(workspace)} />
      <ConfirmationGates
        pendingGoal={pendingGoal}
        pendingBaselineInvocation={pendingBaselineInvocation}
        loading={loading}
        disabled={composerDisabled}
        confirmPendingGoal={confirmPendingGoal}
        confirmToolInvocation={confirmToolInvocation}
      />
      <AgentLog messages={messages} />
      <ProjectTaskComposer
        prompt={prompt}
        setPrompt={setPrompt}
        runPrompt={runPrompt}
        initializeSystemImage={initializeSystemImage}
        invokeProjectAction={invokeProjectAction}
        disabled={composerDisabled}
        actionControlsDisabled={actionControlsDisabled}
      />
    </section>
  )
}

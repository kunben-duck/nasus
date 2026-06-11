import { create } from 'zustand'

type TabMap = Record<string, string>

interface UiState {
  panelTabs: TabMap
  setPanelTab: (viewId: string, tabId: string) => void
}

const defaults: TabMap = {
  welcome: 'Activity',
  build: 'Projects',
  dashboard: 'Alerts',
  documentation: 'Topics',
  projectOverview: 'Context',
  versionSpace: 'Board',
  personalWorkspace: 'Assets',
  knowledge: 'Graph',
  runs: 'Active',
  governance: 'Pending',
}

export const useUiStore = create<UiState>((set) => ({
  panelTabs: defaults,
  setPanelTab: (viewId, tabId) =>
    set((state) => ({
      panelTabs: {
        ...state.panelTabs,
        [viewId]: tabId,
      },
    })),
}))


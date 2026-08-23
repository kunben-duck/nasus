export type StudioSidebarIconName = 'notifications' | 'settings' | 'search' | 'key'

export function StudioSidebarIcon({ name }: { name: StudioSidebarIconName }) {
  return <span className="material-symbols-outlined" aria-hidden="true">{name}</span>
}

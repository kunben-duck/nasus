import type { ReactNode } from 'react'

export type SettingsPanel = 'theme' | 'language' | 'model' | 'notifications' | 'account' | 'members' | 'status'

export type SettingsMenuItem = {
  id?: SettingsPanel
  icon: string
  label: string
  value?: string
  separator?: boolean
}

export type SettingsChoice<T extends string> = {
  value: T
  label: ReactNode
}

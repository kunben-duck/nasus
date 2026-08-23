export type AvatarPresetId =
  | 'yellow_duck'
  | 'city_fox'
  | 'officer_bunny'
  | 'zen_sloth'
  | 'jungle_lion'
  | 'panda_tester'
  | 'koala_builder'
  | 'capybara_lead'

export interface AvatarPreset {
  id: AvatarPresetId
  label: string
  glyph: string
  background: string
}

export const avatarPresets: AvatarPreset[] = [
  {
    id: 'yellow_duck',
    label: 'Yellow Duck',
    glyph: '🦆',
    background: 'linear-gradient(135deg, #ffe06a, #f4a340 58%, #5aa7ff)',
  },
  {
    id: 'city_fox',
    label: 'City Fox',
    glyph: '🦊',
    background: 'linear-gradient(135deg, #ff9b54, #6f88ff 55%, #1f2532)',
  },
  {
    id: 'officer_bunny',
    label: 'Officer Bunny',
    glyph: '🐰',
    background: 'linear-gradient(135deg, #dbeafe, #8aa9ff 54%, #425a89)',
  },
  {
    id: 'zen_sloth',
    label: 'Zen Sloth',
    glyph: '🦥',
    background: 'linear-gradient(135deg, #c6a47e, #7bcf9a 54%, #405044)',
  },
  {
    id: 'jungle_lion',
    label: 'Jungle Lion',
    glyph: '🦁',
    background: 'linear-gradient(135deg, #f7c66a, #c86a3a 54%, #31422d)',
  },
  {
    id: 'panda_tester',
    label: 'Panda Tester',
    glyph: '🐼',
    background: 'linear-gradient(135deg, #f4f6fb, #7f8da3 56%, #222832)',
  },
  {
    id: 'koala_builder',
    label: 'Koala Builder',
    glyph: '🐨',
    background: 'linear-gradient(135deg, #d2d6dc, #8ea3b8 55%, #4b5871)',
  },
  {
    id: 'capybara_lead',
    label: 'Capybara Lead',
    glyph: '🦫',
    background: 'linear-gradient(135deg, #c99162, #76c27d 58%, #406477)',
  },
]

export function findAvatarPreset(id?: string | null): AvatarPreset | undefined {
  return avatarPresets.find((preset) => preset.id === id)
}

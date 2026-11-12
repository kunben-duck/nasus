export const nativeBuildProfiles = {
  'nasus.offline-java21-maven3911.v1': { suffix: '.jar', definition: 'pom.xml', runtime: 'Java', version: '21', tool: 'Maven', toolVersion: '3.9.11' },
  'nasus.offline-python312-zipapp.v1': { suffix: '.pyz', definition: 'pyproject.toml', runtime: 'Python', version: '3.12', tool: 'zipapp', toolVersion: '1' },
} as const
export type NativeBuildAdapter = keyof typeof nativeBuildProfiles
export function nativeBuildProfile(adapter: string) {
  if (!Object.hasOwn(nativeBuildProfiles, adapter)) throw new Error('Unsupported native build adapter')
  return nativeBuildProfiles[adapter as NativeBuildAdapter]
}

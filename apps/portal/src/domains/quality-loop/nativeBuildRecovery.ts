import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireNativeBuild } from './nativeBuildValidation'
import type { NativeBuildAttempt } from './types/nativeBuilds'

type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
export function verifyNativeAttempt(value: unknown): NativeBuildAttempt {
  const v = value as NativeBuildAttempt
  requireNativeBuild(v && ['projectId', 'imageId', 'requestKey'].every((key) => scriptId(v[key as keyof NativeBuildAttempt]))
    && generationDigest(v.imageHash) && generationDigest(v.requestHash) && (v.commandId === undefined || scriptId(v.commandId))
    && Object.keys(v).every((key) => ['projectId', 'imageId', 'imageHash', 'requestKey', 'requestHash', 'commandId'].includes(key)))
  return v
}
export function createNativeRecovery(storage: () => StoragePort, namespace = 'nasus.native-build.v1') {
  const key = (actor: string, project: string, image: string, hash: string) => {
    requireNativeBuild([actor, project, image].every(scriptId) && generationDigest(hash))
    return namespace + ':' + JSON.stringify([actor, project, image, hash])
  }
  const read = (actor: string, project: string, image: string, hash: string) => {
    const raw = storage().getItem(key(actor, project, image, hash))
    if (raw === null) return null
    requireNativeBuild(raw.length <= 4096)
    const value = verifyNativeAttempt(JSON.parse(raw))
    requireNativeBuild(value.projectId === project && value.imageId === image && value.imageHash === hash)
    return value
  }
  const write = (actor: string, value: NativeBuildAttempt) => {
    verifyNativeAttempt(value)
    const name = key(actor, value.projectId, value.imageId, value.imageHash), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireNativeBuild(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, value: NativeBuildAttempt) {
      requireNativeBuild(!read(actor, value.projectId, value.imageId, value.imageHash) && !value.commandId); write(actor, value)
    },
    acknowledge(actor: string, value: NativeBuildAttempt) {
      const prior = read(actor, value.projectId, value.imageId, value.imageHash)
      requireNativeBuild(prior && prior.requestKey === value.requestKey && prior.requestHash === value.requestHash && value.commandId
        && (!prior.commandId || prior.commandId === value.commandId)); write(actor, value)
    },
    clear(actor: string, value: NativeBuildAttempt) {
      const prior = read(actor, value.projectId, value.imageId, value.imageHash)
      requireNativeBuild(prior && generationDigest(value.requestHash) && prior.requestKey === value.requestKey
        && prior.requestHash === value.requestHash && prior.commandId === value.commandId)
      const name = key(actor, value.projectId, value.imageId, value.imageHash); storage().removeItem(name); requireNativeBuild(storage().getItem(name) === null)
    },
  }
}
export const nativeRecovery = createNativeRecovery(() => window.sessionStorage)

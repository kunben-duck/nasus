import { useRef, useState } from 'react'

export function useProjectActionLock() {
  const [activeActionId, setActiveActionId] = useState<string | null>(null)
  const actionLockRef = useRef<string | null>(null)

  async function runLockedAction(actionId: string, operation: () => Promise<void>) {
    if (actionLockRef.current) return
    actionLockRef.current = actionId
    setActiveActionId(actionId)
    try {
      await operation()
    } finally {
      actionLockRef.current = null
      setActiveActionId(null)
    }
  }

  return {
    activeActionId,
    actionRunning: Boolean(activeActionId),
    runLockedAction,
  }
}

export type ProjectActionLockController = ReturnType<typeof useProjectActionLock>

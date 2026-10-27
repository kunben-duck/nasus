import type { Query, QueryClient } from '@tanstack/react-query'

interface PendingRefresh {
  queryKey: string[]
  earlierReads: Map<Query, Query['promise']>
}

export function createConversationQueryRefresh(client: Pick<QueryClient, 'getQueryCache' | 'invalidateQueries'>,
  canRefresh: (queryKey: string[]) => boolean = () => true) {
  const pending = new Map<string, PendingRefresh>(), active = new Set<string>()
  let closed = false, timer: ReturnType<typeof setTimeout> | undefined
  function arm() {
    if (closed || timer || ![...pending.keys()].some((key) => !active.has(key))) return
    timer = setTimeout(flush, 200)
  }
  async function refresh(key: string, { queryKey, earlierReads }: PendingRefresh) {
    if (closed || !canRefresh(queryKey)) return
    active.add(key)
    try {
      const unfinished = new Set([...earlierReads].filter(([query, promise]) =>
        query.state.fetchStatus === 'fetching' && query.promise === promise).map(([query]) => query))
      await client.invalidateQueries({ queryKey }, { cancelRefetch: false })
      // Only reads already running when the event arrived can predate it.
      // A prefix-wide follow-up also restarts later private page readers.
      if (unfinished.size && !closed && canRefresh(queryKey)) await client.invalidateQueries({ queryKey,
        predicate: (query) => unfinished.has(query) && query.state.status !== 'error',
      }, { cancelRefetch: false })
    } catch {
      // The query retains its error state. A later event may request a new read.
    } finally {
      active.delete(key)
      arm()
    }
  }
  function flush() {
    timer = undefined
    for (const [key, refreshRequest] of pending) {
      if (active.has(key)) continue
      pending.delete(key)
      void refresh(key, refreshRequest)
    }
  }
  return {
    schedule(queryKey: string[]) {
      if (closed || !canRefresh(queryKey)) return
      const key = JSON.stringify(queryKey)
      const request = pending.get(key) ?? { queryKey: [...queryKey], earlierReads: new Map() }
      for (const query of client.getQueryCache().findAll({ queryKey, fetchStatus: 'fetching' })) {
        request.earlierReads.set(query, query.promise)
      }
      pending.set(key, request)
      arm()
    },
    close() {
      closed = true
      if (timer) clearTimeout(timer)
      timer = undefined
      pending.clear()
    },
  }
}

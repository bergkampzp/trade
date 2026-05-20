import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchSyncStatus, fetchSyncLogs, triggerSync } from '@/api/sync'
import type { SyncStatusItem, SyncLogItem, SyncResultResponse } from '@/types'

export const useSyncStore = defineStore('sync', () => {
  const sources = ref<SyncStatusItem[]>([])
  const logs = ref<SyncLogItem[]>([])
  const loading = ref(false)
  const running = ref<string | null>(null)

  async function load() {
    loading.value = true
    try {
      const [s, l] = await Promise.all([fetchSyncStatus(), fetchSyncLogs()])
      sources.value = s.sources
      logs.value = l.logs
    } finally {
      loading.value = false
    }
  }

  async function sync(source: string): Promise<SyncResultResponse> {
    running.value = source
    try {
      const result = await triggerSync(source)
      await load()
      return result
    } finally {
      running.value = null
    }
  }

  return { sources, logs, loading, running, load, sync }
})

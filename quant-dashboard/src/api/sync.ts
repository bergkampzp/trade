import { api } from './client'
import type {
  SyncStatusResponse, SyncLogsResponse, SyncResultResponse
} from '@/types'

export function fetchSyncStatus(lang = 'zh_CN') {
  return api<SyncStatusResponse>(`/quant/sync/status?lang=${lang}`)
}

export function fetchSyncLogs() {
  return api<SyncLogsResponse>('/quant/sync/logs')
}

export function triggerSync(source: string) {
  return api<SyncResultResponse>(`/quant/sync/${source}`, { method: 'POST' })
}

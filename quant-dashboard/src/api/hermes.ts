// api/hermes.ts — AI天团 WebChat API 层

import type { ChatRequest, SessionDetail, SessionSummary, SkillInfo, StreamEvent } from '../types/hermes'

const BASE = '/api/v1/hermes'
const headers = () => ({
  Authorization: 'Basic ' + btoa('quant:quant123'),
  'Content-Type': 'application/json',
})

export async function fetchSkills(): Promise<SkillInfo[]> {
  const res = await fetch(`${BASE}/skills`, { headers: headers() })
  if (!res.ok) throw new Error(`Skills: ${res.status}`)
  return res.json()
}

export async function createSession(title: string, skill?: string): Promise<{ session_id: string; title: string }> {
  const res = await fetch(`${BASE}/session/new`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ title, skill }),
  })
  if (!res.ok) throw new Error(`New session: ${res.status}`)
  return res.json()
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${BASE}/sessions`, { headers: headers() })
  if (!res.ok) throw new Error(`Sessions: ${res.status}`)
  return res.json()
}

export async function loadSession(sid: string): Promise<SessionDetail> {
  const res = await fetch(`${BASE}/session/${sid}`, { headers: headers() })
  if (!res.ok) throw new Error(`Load session: ${res.status}`)
  return res.json()
}

export async function deleteSession(sid: string): Promise<void> {
  const res = await fetch(`${BASE}/session/${sid}`, { method: 'DELETE', headers: headers() })
  if (!res.ok) throw new Error(`Delete session: ${res.status}`)
}

export async function appendMessage(sid: string, msg: { role: string; content: string; skill?: string }): Promise<void> {
  const res = await fetch(`${BASE}/session/${sid}/append`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(msg),
  })
  if (!res.ok) throw new Error(`Append: ${res.status}`)
}

/**
 * SSE stream for chat. Returns an AbortController for cancellation.
 */
export function streamChat(
  req: ChatRequest,
  onEvent: (evt: StreamEvent) => void,
  onError: (err: string) => void,
  onDone: () => void,
): AbortController {
  const abort = new AbortController()

  fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: {
      ...headers(),
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(req),
    signal: abort.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) { onError('No reader'); return }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const evt: StreamEvent = JSON.parse(line.slice(6))
              onEvent(evt)
              if (evt.type === 'done') return
            } catch { /* skip malformed */ }
          }
        }
      }
      onDone()
    })
    .catch((e) => {
      if (e.name !== 'AbortError') {
        onError(e.message)
      }
    })

  return abort
}

export async function uploadFile(file: File): Promise<{ status: string; file_name: string; chunks_added: number }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    headers: { Authorization: 'Basic ' + btoa('quant:quant123') },
    body: form,
  })
  if (!res.ok) throw new Error(`Upload: ${res.status}`)
  return res.json()
}

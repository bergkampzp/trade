// types/hermes.ts — AI天团 WebChat 类型定义

export interface SkillInfo {
  name: string
  label: string
  description: string
  icon: string
  color: string
  tags: string[]
  suggestions: string[]
}

export interface ChatRequest {
  message: string
  skill?: string
  session_id?: string
  attachments?: string[]
}

export interface SessionSummary {
  id: string
  title: string
  skill?: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface SessionDetail {
  id: string
  title: string
  skill?: string
  messages: ChatMessage[]
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  skill?: string
  timestamp?: string
}

export interface Citation {
  source: string
  file_name: string
  text: string
  score: number
}

export type StreamEvent =
  | { type: 'text'; content: string }
  | { type: 'citation'; source: string; file_name: string; text: string; score: number }
  | { type: 'error'; message: string }
  | { type: 'done' }

// UI state
export type ChatStatus = 'empty' | 'loading' | 'streaming' | 'error' | 'ready'

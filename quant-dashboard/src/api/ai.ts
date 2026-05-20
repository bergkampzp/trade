import { api } from './client'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ToolCall {
  tool: string
  args: Record<string, any>
  result: string
}

export interface ChatResponse {
  response: string
  tool_calls: ToolCall[]
}

export interface SkillInfo {
  name: string
  description: string
  version: string
  tags: string[]
}

export function sendChatMessage(messages: ChatMessage[], pair?: string, skill?: string) {
  return api<ChatResponse>('/quant/chat', {
    method: 'POST',
    body: { messages, pair: pair || 'BTC/USDT', skill: skill || '' },
  })
}

export function fetchSkills() {
  return api<{ skills: SkillInfo[] }>('/quant/skills')
}

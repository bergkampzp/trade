import { ofetch } from 'ofetch'

const API_BASE = 'http://localhost:20080/api/v1'

let _token: string | null = null
let _loginPromise: Promise<string> | null = null

// Basic Auth credentials for fallback
const CREDENTIALS=btoa('...23')

export const api = ofetch.create({
  baseURL: API_BASE,
  retry: 1,
  timeout: 300000,  // 5分钟超时，辩论分析LLM调用可能需要
  onRequest({ options }) {
    const existing = (options.headers || {}) as Record<string, string>
    if (!existing['Authorization']) {
      if (_token) {
        options.headers = { ...existing, Authorization: `Bearer ${_token}` }
      } else {
        // Fallback to Basic Auth
        options.headers = { ...existing, Authorization: `Basic ${CREDENTIALS}` }
      }
    }
  },
  async onResponseError({ response, options }) {
    if (response.status === 401 && _token) {
      // Token expired, re-login
      _token = null
      localStorage.removeItem('ft_token')
      await login('quant', 'quant123')
      const existing = (options.headers || {}) as Record<string, string>
      options.headers = { ...existing, Authorization: `Bearer ${_token}` }
    }
  },
})

export async function login(username: string, password: string): Promise<string> {
  if (_loginPromise) return _loginPromise
  _loginPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/token/login`, {
        method: 'POST',
        headers: { Authorization: 'Basic ' + btoa(`${username}:${password}`) },
      })
      if (!res.ok) throw new Error(`Login failed: ${res.status}`)
      const data = await res.json()
      _token = data.access_token
      localStorage.setItem('ft_token', _token!)
      return _token!
    } finally {
      _loginPromise = null
    }
  })()
  return _loginPromise
}

export function restoreToken(): boolean {
  const saved = localStorage.getItem('ft_token')
  if (saved) {
    _token = saved
    return true
  }
  return false
}

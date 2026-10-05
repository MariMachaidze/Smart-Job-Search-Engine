/**
 * The ONE module that knows how HTTP requests actually leave the browser.
 *
 * Every other file calls `apiFetch`/`apiUpload`/`streamChatMessage` (or the
 * typed wrappers in src/api/endpoints.ts, which call these) -- nothing else
 * touches `fetch` directly, reads `VITE_API_BASE_URL`, or looks at
 * localStorage for the token. That's what makes swapping mocked responses
 * for the real backend a change contained to this file (plus turning off
 * the MSW worker in src/main.tsx): call sites, types, and components never
 * change.
 *
 * Base URL: VITE_API_BASE_URL (default '' -> same-origin, so a dev proxy or
 * same-host deploy both work without edits). Auth: JWT stored in
 * localStorage under TOKEN_STORAGE_KEY, attached as `Authorization: Bearer
 * <token>` on every call automatically.
 */

const TOKEN_STORAGE_KEY = 'sjse_auth_token'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    // localStorage unavailable (private mode, etc.) -- the session just
    // won't persist across reloads; not fatal.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // ignore
  }
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseErrorBody(res: Response): Promise<unknown> {
  try {
    return await res.clone().json()
  } catch {
    try {
      return await res.text()
    } catch {
      return null
    }
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export interface ApiFetchOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

/** JSON request/response helper used by every non-upload, non-streaming
 * call. Throws ApiError on any non-2xx response. */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { method = 'GET', body, signal } = options
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    signal,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...authHeaders(),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    const errBody = await parseErrorBody(res)
    throw new ApiError(res.status, errorMessage(errBody, `Request failed: ${res.status}`), errBody)
  }

  if (res.status === 204) {
    return undefined as T
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** multipart/form-data upload (resume PDF). Deliberately does not set
 * Content-Type -- the browser sets the multipart boundary itself. */
export async function apiUpload<T>(path: string, file: File, fieldName = 'file'): Promise<T> {
  const form = new FormData()
  form.append(fieldName, file)
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: form,
  })
  if (!res.ok) {
    const errBody = await parseErrorBody(res)
    throw new ApiError(res.status, errorMessage(errBody, `Upload failed: ${res.status}`), errBody)
  }
  return (await res.json()) as T
}

/**
 * Streams POST /chat/sessions/{id}/message. The documented contract (plan
 * section 12) says the reply is "streamed via SSE" from a route the client
 * reaches with a plain POST -- the browser's native `EventSource` can't
 * send a POST body, so this reads the response body as a stream and parses
 * standard SSE framing (`data: <json>\n\n`) out of it by hand. If/when the
 * real backend instead exposes a GET+EventSource endpoint, only this
 * function needs to change.
 *
 * `onEvent` fires once per parsed ChatStreamEvent; the returned promise
 * resolves once the stream ends (or rejects on a network-level failure --
 * an in-band {type:"error"} event is delivered to onEvent, not a rejection).
 */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: (event: import('./types').ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/chat/sessions/${sessionId}/message`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...authHeaders(),
    },
    body: JSON.stringify({ content }),
  })

  if (!res.ok || !res.body) {
    const errBody = await parseErrorBody(res)
    throw new ApiError(res.status, errorMessage(errBody, `Chat stream failed: ${res.status}`), errBody)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line; each frame may have
    // multiple `data:` lines (rare here, but handled for correctness).
    let frameEnd: number
    while ((frameEnd = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, frameEnd)
      buffer = buffer.slice(frameEnd + 2)
      const dataLines = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
      if (dataLines.length === 0) continue
      const payload = dataLines.join('\n')
      if (payload === '[DONE]') continue
      try {
        onEvent(JSON.parse(payload) as import('./types').ChatStreamEvent)
      } catch {
        // Malformed/partial frame -- skip rather than crash the stream.
      }
    }
  }
}

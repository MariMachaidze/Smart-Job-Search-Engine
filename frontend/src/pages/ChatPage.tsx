import { useEffect, useRef, useState, type FormEvent } from 'react'
import { chatApi, jobsApi } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { ChatMessage, ChatSessionSummary } from '../api/types'
import { ChatMessageBubble } from '../components/ChatMessageBubble'

export function ChatPage() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const threadRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    void loadSessions()
  }, [])

  useEffect(() => {
    const el = threadRef.current
    // jsdom (used in component tests) doesn't implement Element.scrollTo --
    // guard so tests don't crash on every message update.
    if (el && typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight })
    }
  }, [messages])

  async function loadSessions(selectFirst = true) {
    try {
      const list = await chatApi.listSessions()
      setSessions(list)
      if (selectFirst && list.length > 0 && !activeSessionId) {
        void selectSession(list[0].session_id)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load chat sessions.')
    }
  }

  async function selectSession(sessionId: string) {
    setActiveSessionId(sessionId)
    setError(null)
    try {
      const session = await chatApi.getSession(sessionId)
      setMessages(session.messages)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load conversation.')
    }
  }

  async function handleNewSession() {
    try {
      const session = await chatApi.createSession()
      setSessions((prev) => [{ session_id: session.session_id, title: session.title, created_at: session.created_at, updated_at: session.updated_at }, ...prev])
      setActiveSessionId(session.session_id)
      setMessages([])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to start a new conversation.')
    }
  }

  async function handleDeleteSession(sessionId: string) {
    try {
      await chatApi.deleteSession(sessionId)
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId))
      if (activeSessionId === sessionId) {
        setActiveSessionId(null)
        setMessages([])
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to delete conversation.')
    }
  }

  async function handleSend(e: FormEvent) {
    e.preventDefault()
    const content = draft.trim()
    if (!content) return

    let sessionId = activeSessionId
    if (!sessionId) {
      const session = await chatApi.createSession()
      sessionId = session.session_id
      setActiveSessionId(sessionId)
      setSessions((prev) => [{ session_id: session.session_id, title: session.title, created_at: session.created_at, updated_at: session.updated_at }, ...prev])
    }

    setDraft('')
    setSending(true)
    setError(null)
    setMessages((prev) => [...prev, { role: 'user', content, timestamp: new Date().toISOString() }])
    // Placeholder assistant bubble, filled in as tokens stream in.
    setMessages((prev) => [...prev, { role: 'assistant', content: '', timestamp: new Date().toISOString() }])

    try {
      await chatApi.streamMessage(sessionId, content, (event) => {
        if (event.type === 'token') {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, content: last.content + event.content }
            return next
          })
        } else if (event.type === 'jobs') {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, jobs: event.jobs }
            return next
          })
        } else if (event.type === 'error') {
          setError(event.message)
        }
      })
      void loadSessions(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to send message.')
    } finally {
      setSending(false)
    }
  }

  async function handleRateJob(jobId: string, feedback: 'relevant' | 'not_relevant') {
    try {
      await jobsApi.rate(jobId, { feedback })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save feedback.')
    }
  }

  async function handleTailorJob(jobId: string) {
    try {
      await jobsApi.tailor(jobId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to tailor resume.')
    }
  }

  return (
    <div className="page">
      <h1 className="page-title">Chat</h1>
      <p className="page-subtitle">Ask it to find jobs, rate postings, tailor a resume, or update your tracker.</p>
      {error && <p className="error-text">{error}</p>}

      <div className="chat-layout">
        <aside className="chat-sidebar">
          <button type="button" className="btn btn-primary btn-small" onClick={handleNewSession}>
            + New chat
          </button>
          {sessions.length === 0 && <p className="empty-state">No conversations yet.</p>}
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`chat-session-item ${s.session_id === activeSessionId ? 'active' : ''}`}
              onClick={() => selectSession(s.session_id)}
              role="button"
              tabIndex={0}
            >
              <span>{s.title}</span>
              <button
                type="button"
                className="btn btn-small"
                onClick={(e) => {
                  e.stopPropagation()
                  void handleDeleteSession(s.session_id)
                }}
                aria-label={`Delete ${s.title}`}
              >
                ✕
              </button>
            </div>
          ))}
        </aside>

        <section className="chat-main">
          <div className="chat-thread" ref={threadRef}>
            {messages.length === 0 && <p className="empty-state">Say hello, or ask "find me new jobs".</p>}
            {messages.map((m, i) => (
              <ChatMessageBubble key={i} message={m} onRateJob={handleRateJob} onTailorJob={handleTailorJob} />
            ))}
          </div>
          <form className="chat-input-row" onSubmit={handleSend}>
            <input
              type="text"
              placeholder="Type a message…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={sending}
              aria-label="Chat message"
            />
            <button type="submit" className="btn btn-primary" disabled={sending || !draft.trim()}>
              Send
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}

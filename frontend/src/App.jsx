import { useEffect, useRef, useState } from 'react'
import { askQuestion, getMessages, listConversations } from './api.js'
import Answer from './components/Answer.jsx'
import Composer from './components/Composer.jsx'
import Sidebar from './components/Sidebar.jsx'

const EXAMPLES = [
  'What is the total revenue?',
  'Show revenue by category',
  'Top 5 products by quantity sold',
  'Revenue by month this year',
]

// The whole page. It owns the state (which chat is open, its messages, whether
// we are waiting) and hands pieces of it to the smaller components.
export default function App() {
  const [conversations, setConversations] = useState([]) // for the sidebar
  const [sidebarError, setSidebarError] = useState('')
  const [activeId, setActiveId] = useState(null) // null = a new, unsaved chat
  const [messages, setMessages] = useState([]) // what is on screen
  const [thinking, setThinking] = useState(false) // waiting for an answer
  const [loadingChat, setLoadingChat] = useState(false) // opening an old chat
  const [sidebarOpen, setSidebarOpen] = useState(false) // small screens only

  // Goes up by one whenever the user switches chat. A reply that arrives for
  // a chat the user has already left is recognised by its old number and dropped.
  const visit = useRef(0)
  const nextKey = useRef(0) // gives every message a unique key for React
  const bottom = useRef(null)

  function withKey(message) {
    nextKey.current += 1
    return { ...message, key: nextKey.current }
  }

  async function refreshConversations() {
    try {
      setConversations(await listConversations())
      setSidebarError('')
    } catch (error) {
      setSidebarError(error.message)
    }
  }

  // Load the list of chats once, when the page opens.
  useEffect(() => {
    listConversations()
      .then(setConversations)
      .catch((error) => setSidebarError(error.message))
  }, [])

  // Keep the newest message in view.
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [messages, thinking])

  function startNewChat() {
    visit.current += 1
    setActiveId(null)
    setMessages([])
    setThinking(false)
    setLoadingChat(false)
    setSidebarOpen(false)
  }

  async function openConversation(id) {
    const thisVisit = (visit.current += 1)
    setActiveId(id)
    setMessages([])
    setThinking(false)
    setLoadingChat(true)
    setSidebarOpen(false)
    try {
      const saved = await getMessages(id)
      if (visit.current !== thisVisit) return // the user moved on meanwhile
      // Saved messages hold text and SQL only; the rows were never stored.
      setMessages(
        saved.map((message) =>
          withKey(
            message.role === 'user'
              ? { role: 'user', text: message.content }
              : { role: 'assistant', summary: message.content, sql: message.sql_used },
          ),
        ),
      )
    } catch (error) {
      if (visit.current === thisVisit) setMessages([withKey({ role: 'error', text: error.message })])
    } finally {
      if (visit.current === thisVisit) setLoadingChat(false)
    }
  }

  async function send(question) {
    if (thinking) return
    const thisVisit = visit.current
    setMessages((current) => [...current, withKey({ role: 'user', text: question })])
    setThinking(true)
    try {
      const result = await askQuestion(question, activeId)
      refreshConversations() // a new chat appears, or this one moves to the top
      if (visit.current !== thisVisit) return
      setActiveId(result.conversation_id)
      setMessages((current) => [...current, withKey({ role: 'assistant', ...result })])
    } catch (error) {
      if (visit.current !== thisVisit) return
      setMessages((current) => [...current, withKey({ role: 'error', text: error.message })])
    } finally {
      if (visit.current === thisVisit) setThinking(false)
    }
  }

  const isEmpty = messages.length === 0 && !thinking && !loadingChat

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        error={sidebarError}
        open={sidebarOpen}
        onNewChat={startNewChat}
        onSelect={openConversation}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button type="button" className="menu" aria-label="Show conversations" onClick={() => setSidebarOpen(true)}>
            <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <span>Shop Data Chat</span>
        </header>

        <div className="scroll">
          <div className="column">
            {isEmpty && (
              <section className="welcome">
                <h1>What would you like to know?</h1>
                <p>Ask a question about the shop&apos;s customers, products and orders in plain English.</p>
                <div className="examples">
                  {EXAMPLES.map((example) => (
                    <button key={example} type="button" onClick={() => send(example)}>
                      {example}
                    </button>
                  ))}
                </div>
              </section>
            )}

            {loadingChat && <p className="status">Loading conversation…</p>}

            {messages.map((message) => {
              if (message.role === 'user') {
                return (
                  <div key={message.key} className="message user">
                    <p>{message.text}</p>
                  </div>
                )
              }
              if (message.role === 'error') {
                return (
                  <div key={message.key} className="error" role="alert">
                    {message.text}
                  </div>
                )
              }
              return <Answer key={message.key} answer={message} busy={thinking} onFollowUp={send} />
            })}

            {thinking && (
              <div className="message assistant" role="status">
                <div className="avatar" aria-hidden="true">AI</div>
                <p className="thinking">
                  Thinking<span>.</span><span>.</span><span>.</span>
                </p>
              </div>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <footer className="composer-area">
          <div className="column">
            <Composer disabled={thinking || loadingChat} onSend={send} />
            <p className="hint">Read-only: the assistant can look at data but never change it.</p>
          </div>
        </footer>
      </main>
    </div>
  )
}

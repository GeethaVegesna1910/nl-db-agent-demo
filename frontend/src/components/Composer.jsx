import { useState } from 'react'

const MAX_LENGTH = 500 // the API rejects longer questions

// The input box at the bottom. Enter sends; Shift+Enter starts a new line.
export default function Composer({ disabled, onSend }) {
  const [text, setText] = useState('')
  const canSend = !disabled && text.trim().length > 0

  function send() {
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault() // don't add a new line
      send()
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
    >
      <textarea
        aria-label="Ask a question"
        placeholder="Ask about revenue, orders, products or customers…"
        rows={1}
        maxLength={MAX_LENGTH}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <button type="submit" className="send" disabled={!canSend} aria-label="Send">
        <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
          <path d="M10 16V4M10 4l-5 5M10 4l5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </form>
  )
}

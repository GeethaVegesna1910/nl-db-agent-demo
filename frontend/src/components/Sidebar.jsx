import { formatWhen } from '../format.js'

// The left column: a "New chat" button and the list of past chats.
export default function Sidebar({ conversations, activeId, error, open, onNewChat, onSelect }) {
  return (
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`} aria-label="Conversations">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22">
            <rect x="6" y="17" width="5" height="9" rx="1.5" />
            <rect x="13.5" y="11" width="5" height="15" rx="1.5" />
            <rect x="21" y="6" width="5" height="20" rx="1.5" />
          </svg>
        </span>
        Shop Data Chat
      </div>

      <button type="button" className="new-chat" onClick={onNewChat}>
        <span aria-hidden="true">+</span> New chat
      </button>

      <h2 className="sidebar-heading">Recent</h2>

      {error && <p className="sidebar-note">{error}</p>}
      {!error && conversations.length === 0 && (
        <p className="sidebar-note">No chats yet. Ask your first question.</p>
      )}

      <ul className="chat-list">
        {conversations.map((chat) => (
          <li key={chat.id}>
            <button
              type="button"
              className={`chat-item ${chat.id === activeId ? 'chat-item-active' : ''}`}
              aria-current={chat.id === activeId ? 'true' : undefined}
              onClick={() => onSelect(chat.id)}
            >
              <span className="chat-title">{chat.title || 'Untitled chat'}</span>
              <span className="chat-when">{formatWhen(chat.last_active_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}

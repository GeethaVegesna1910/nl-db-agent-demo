// All the calls to the API live here, so the components never deal with
// addresses, JSON or network errors themselves.

// Where the API runs. Set VITE_API_URL in frontend/.env to change it.
export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

// PLACEHOLDER until real sign-in exists: everyone is the same "demo" user.
export const USER_ID = 'demo'

export const CANNOT_REACH_SERVER =
  "I can't reach the server right now. Please check that the API is running, then try again."
export const SERVER_PROBLEM = 'Sorry, something went wrong on our side. Please try again.'

// Send one request and return the JSON reply. Any failure becomes an Error
// whose message is safe and friendly enough to show to the user.
async function request(path, options) {
  let response
  try {
    response = await fetch(API_URL + path, options)
  } catch {
    // fetch itself failed: the server is down or the address is wrong.
    throw new Error(CANNOT_REACH_SERVER)
  }

  let data = null
  try {
    data = await response.json()
  } catch {
    // The reply was not JSON. Handled just below.
  }

  if (!response.ok || data === null) {
    // The API puts a readable sentence in "detail" (for example
    // "The question must not be empty."). Use it when there is one.
    const detail = data && typeof data.detail === 'string' ? data.detail : SERVER_PROBLEM
    throw new Error(detail)
  }
  return data
}

// Ask a question. Leave conversationId empty to start a new chat.
export function askQuestion(question, conversationId) {
  return request('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      conversation_id: conversationId ?? null,
      user_id: USER_ID,
    }),
  })
}

// The user's past chats, newest first.
export async function listConversations() {
  const data = await request(`/conversations?user_id=${encodeURIComponent(USER_ID)}`)
  return data.conversations
}

// The saved messages of one chat, oldest first.
export async function getMessages(conversationId) {
  const data = await request(
    `/conversations/${conversationId}/messages?user_id=${encodeURIComponent(USER_ID)}`,
  )
  return data.messages
}

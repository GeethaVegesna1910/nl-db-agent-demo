// Tests for the chat page. The API is replaced by pretend functions, so no
// server is needed and nothing is really sent.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'
import { askQuestion, getMessages, listConversations } from './api.js'

// Every function exported by api.js becomes a pretend one we can control.
vi.mock('./api.js')

const REVENUE_BY_CATEGORY = {
  conversation_id: 7,
  summary: 'Furniture is the top category by revenue with $184,276.54 (32% of the total).',
  sql: 'SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue FROM order_items oi',
  columns: ['category', 'revenue'],
  rows: [
    ['Furniture', 184276.54],
    ['Electronics', 157065.54],
  ],
  chart: 'bar',
  highlights: ['Furniture makes up 54% of the total, more than everything else combined.'],
  follow_ups: ['Show it by country instead', 'How has it changed by month?'],
}

// Type a question into the box and press Enter.
async function ask(user, question) {
  await user.type(screen.getByLabelText('Ask a question'), `${question}{Enter}`)
}

beforeEach(() => {
  vi.resetAllMocks()
  listConversations.mockResolvedValue([])
  getMessages.mockResolvedValue([])
})

describe('the chat page', () => {
  it('shows the summary and a table for an answer', async () => {
    askQuestion.mockResolvedValue(REVENUE_BY_CATEGORY)
    const user = userEvent.setup()
    render(<App />)

    await ask(user, 'show revenue by category')

    // The question was sent to the API as a brand new chat...
    expect(askQuestion).toHaveBeenCalledWith('show revenue by category', null)
    // ...and the answer is on the page: summary, table, highlight and SQL.
    expect(await screen.findByText(REVENUE_BY_CATEGORY.summary)).toBeInTheDocument()
    const table = within(screen.getByRole('table'))
    expect(table.getByText('Category')).toBeInTheDocument()
    expect(table.getByText('Furniture')).toBeInTheDocument()
    expect(table.getByText('$184,276.54')).toBeInTheDocument()
    expect(screen.getByText(REVENUE_BY_CATEGORY.highlights[0])).toBeInTheDocument()
    expect(screen.getByText('Show SQL')).toBeInTheDocument()
  })

  it('notes how many rows are hidden when there are more than 20', async () => {
    const rows = Array.from({ length: 25 }, (_, i) => [`Product ${i + 1}`, 100 - i])
    askQuestion.mockResolvedValue({
      ...REVENUE_BY_CATEGORY, chart: 'table', columns: ['name', 'units'], rows, highlights: [],
    })
    const user = userEvent.setup()
    render(<App />)

    await ask(user, 'list products')

    expect(await screen.findByText('5 more rows not shown')).toBeInTheDocument()
    expect(screen.getByText('Product 20')).toBeInTheDocument()
    expect(screen.queryByText('Product 21')).not.toBeInTheDocument()
  })

  it('sends the question when a follow-up button is clicked', async () => {
    askQuestion.mockResolvedValue(REVENUE_BY_CATEGORY)
    const user = userEvent.setup()
    render(<App />)
    await ask(user, 'show revenue by category')

    await user.click(await screen.findByRole('button', { name: 'Show it by country instead' }))

    // Same conversation (id 7), so the agent knows what "it" means.
    expect(askQuestion).toHaveBeenLastCalledWith('Show it by country instead', 7)
    // The clicked suggestion also appears as the user's own message.
    expect(screen.getAllByText('Show it by country instead').length).toBeGreaterThan(1)
  })

  it('shows a friendly message when the API is down', async () => {
    askQuestion.mockRejectedValue(new Error("I can't reach the server right now."))
    const user = userEvent.setup()
    render(<App />)

    await ask(user, 'total revenue')

    expect(await screen.findByRole('alert')).toHaveTextContent("I can't reach the server right now.")
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument()
  })

  it('shows a refusal as a polite sentence with no table or SQL', async () => {
    askQuestion.mockResolvedValue({
      conversation_id: 7, summary: "I can only read data, so I can't delete orders.",
      sql: null, columns: [], rows: [], chart: null, highlights: [], follow_ups: [],
    })
    const user = userEvent.setup()
    render(<App />)

    await ask(user, 'delete all orders')

    expect(await screen.findByText("I can only read data, so I can't delete orders.")).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('Show SQL')).not.toBeInTheDocument()
  })

  it('reopens an old conversation with its saved text and SQL', async () => {
    listConversations.mockResolvedValue([
      { id: 3, title: 'How many orders were cancelled?', last_active_at: '2026-10-02T10:00:00Z' },
    ])
    getMessages.mockResolvedValue([
      { role: 'user', content: 'How many orders were cancelled?', sql_used: null },
      { role: 'assistant', content: 'Cancelled order count is 179.', sql_used: "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'" },
    ])
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /How many orders were cancelled\?/ }))

    expect(getMessages).toHaveBeenCalledWith(3)
    expect(await screen.findByText('Cancelled order count is 179.')).toBeInTheDocument()
    expect(screen.getByText("SELECT COUNT(*) FROM orders WHERE status = 'cancelled'")).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument() // rows are not stored
  })
})

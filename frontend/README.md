# Chat website

A React + Vite front end for the natural-language database agent.

```bash
cp .env.example .env   # then set VITE_API_URL to where the API runs
npm install
npm run dev            # http://localhost:5173
npm test               # Vitest + Testing Library (the API is mocked)
npm run build          # production build into dist/
```

## Where things are

| File | What it does |
| --- | --- |
| `src/api.js` | The three calls to the API, and friendly error messages |
| `src/format.js` | Turns raw values into readable numbers, money and dates |
| `src/App.jsx` | Holds the page's state: chats, messages, "thinking" |
| `src/components/Sidebar.jsx` | "New chat" and the list of past chats |
| `src/components/Answer.jsx` | One answer: summary, chart, table, highlights, SQL, suggestions |
| `src/components/ResultChart.jsx` | Bar chart, line chart or big number (recharts) |
| `src/components/ResultTable.jsx` | The first 20 rows as a table |
| `src/components/Composer.jsx` | The input box at the bottom |

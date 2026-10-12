import ResultChart from './ResultChart.jsx'
import ResultTable from './ResultTable.jsx'

// One answer from the agent. A fresh answer has everything; an answer loaded
// from an old chat only has its text and SQL (rows are not stored), and a
// refused question only has its polite reason. Each part below is shown only
// when there is something to show.
export default function Answer({ answer, busy, onFollowUp }) {
  const { summary, sql, chart, columns = [], rows = [], highlights = [], follow_ups: followUps = [] } = answer
  const hasRows = rows.length > 0
  // A lone figure is already shown as the big number; a one-cell table adds nothing.
  const showTable = hasRows && !(chart === 'number' && rows.length === 1 && columns.length === 1)

  return (
    <article className="message assistant">
      <div className="avatar" aria-hidden="true">AI</div>
      <div className="answer">
        <p className="summary">{summary}</p>

        {hasRows && <ResultChart chart={chart} columns={columns} rows={rows} />}

        {highlights.length > 0 && (
          <div className="highlights" role="note">
            <strong>Worth noticing</strong>
            <ul>
              {highlights.map((highlight) => (
                <li key={highlight}>{highlight}</li>
              ))}
            </ul>
          </div>
        )}

        {showTable && <ResultTable columns={columns} rows={rows} />}

        {sql && (
          <details className="sql">
            <summary>Show SQL</summary>
            <pre>
              <code>{sql}</code>
            </pre>
          </details>
        )}

        {followUps.length > 0 && (
          <div className="follow-ups" aria-label="Suggested questions">
            {followUps.map((question) => (
              <button key={question} type="button" disabled={busy} onClick={() => onFollowUp(question)}>
                {question}
              </button>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}

import { formatCell, isIdColumn, isNumber, prettyColumn } from '../format.js'

const MAX_ROWS = 20 // show the first 20 rows, then a note about the rest

export default function ResultTable({ columns, rows }) {
  const shown = rows.slice(0, MAX_ROWS)
  const hidden = rows.length - shown.length
  // Numbers line up better on the right, like in a spreadsheet.
  const isNumeric = columns.map(
    (column, i) => !isIdColumn(column) && rows.some((row) => isNumber(row[i])),
  )

  return (
    <div className="table-block">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((column, i) => (
                <th key={column + i} className={isNumeric[i] ? 'cell-number' : undefined}>
                  {prettyColumn(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, r) => (
              <tr key={r}>
                {row.map((cell, i) => (
                  <td key={i} className={isNumeric[i] ? 'cell-number' : undefined}>
                    {formatCell(cell, columns[i])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p className="table-note">
          {hidden.toLocaleString('en-US')} more {hidden === 1 ? 'row' : 'rows'} not shown
        </p>
      )}
    </div>
  )
}

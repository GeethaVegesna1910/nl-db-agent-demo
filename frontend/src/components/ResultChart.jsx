import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  formatCell, formatCompact, formatNumber, isIdColumn, isNumber, pickChartColumns, prettyColumn,
  shortDate,
} from '../format.js'

// Draws the picture the API chose for this answer:
//   "number" -> one big figure      "bar"  -> horizontal bars, one per category
//   "line"   -> a line over time    anything else -> nothing (the table is enough)
export default function ResultChart({ chart, columns, rows }) {
  if (chart === 'number') return <BigNumber columns={columns} row={rows[0]} />
  if (chart !== 'bar' && chart !== 'line') return null

  const picked = pickChartColumns(columns, rows)
  if (!picked) return null
  const valueColumn = columns[picked.valueIndex]
  // recharts wants a list of objects: [{ label: 'Furniture', value: 184276.54 }, ...]
  const data = rows
    .filter((row) => isNumber(row[picked.valueIndex]))
    .map((row) => ({
      label: formatCell(row[picked.labelIndex], columns[picked.labelIndex]),
      value: row[picked.valueIndex],
    }))
  if (data.length === 0) return null

  const axisText = { fill: 'var(--text-muted)', fontSize: 12 }
  const tooltip = (
    <Tooltip
      cursor={chart === 'bar' ? { fill: 'var(--hover)' } : { stroke: 'var(--border-strong)' }}
      content={<ChartTooltip valueColumn={valueColumn} />}
    />
  )

  if (chart === 'line') {
    return (
      <figure className="chart" aria-label={`Line chart of ${prettyColumn(valueColumn)}`}>
        <figcaption>{prettyColumn(valueColumn)} over time</figcaption>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="label" tick={axisText} tickLine={false} axisLine={{ stroke: 'var(--border-strong)' }} minTickGap={24} tickFormatter={shortDate} />
            <YAxis tick={axisText} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => formatCompact(v, valueColumn)} />
            {tooltip}
            <Line
              dataKey="value"
              stroke="var(--series-1)"
              strokeWidth={2}
              // Dots help when there are few points; with many they turn into clutter.
              dot={data.length <= 24 ? { r: 3, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 } : false}
              activeDot={{ r: 5, stroke: 'var(--surface)', strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </figure>
    )
  }

  // Bars run sideways so long names (product names, say) stay readable.
  const longestLabel = Math.max(...data.map((d) => d.label.length))
  const labelWidth = Math.min(200, Math.max(60, longestLabel * 7 + 12))
  return (
    <figure className="chart" aria-label={`Bar chart of ${prettyColumn(valueColumn)}`}>
      <figcaption>
        {prettyColumn(valueColumn)} by {prettyColumn(columns[picked.labelIndex]).toLowerCase()}
      </figcaption>
      <ResponsiveContainer width="100%" height={data.length * 34 + 36}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 0 }}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis type="number" tick={axisText} tickLine={false} axisLine={false} tickFormatter={(v) => formatCompact(v, valueColumn)} />
          <YAxis type="category" dataKey="label" width={labelWidth} tick={{ ...axisText, fill: 'var(--text-secondary)' }} tickLine={false} axisLine={{ stroke: 'var(--border-strong)' }} interval={0} />
          {tooltip}
          <Bar dataKey="value" fill="var(--series-1)" barSize={18} radius={[0, 4, 4, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

// One headline figure, e.g. "$581,294.51" with "Total revenue" underneath.
function BigNumber({ columns, row }) {
  const valueIndex = columns.findIndex((column, i) => !isIdColumn(column) && isNumber(row[i]))
  if (valueIndex === -1) return null
  // If the row also names something ("USA"), show it next to the column name.
  const name = row.find((cell) => typeof cell === 'string')
  return (
    <div className="big-number">
      <div className="big-number-value">{formatNumber(row[valueIndex], columns[valueIndex])}</div>
      <div className="big-number-label">
        {prettyColumn(columns[valueIndex])}
        {name ? ` · ${name}` : ''}
      </div>
    </div>
  )
}

// The little box that follows the mouse over a chart.
function ChartTooltip({ active, payload, valueColumn }) {
  if (!active || !payload || payload.length === 0) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{point.label}</div>
      <div className="chart-tooltip-value">{formatNumber(point.value, valueColumn)}</div>
    </div>
  )
}

import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ScatterChart,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { format } from 'date-fns'

/* Distinct colours for up to 8 symbols in the overview scatter chart */
const SYMBOL_COLORS = {
  AAPL: '#3b82f6', MSFT: '#10b981', GOOGL: '#f59e0b',
  AMZN: '#8b5cf6', TSLA: '#ef4444', META: '#06b6d4',
  NVDA: '#f97316', SPY:  '#84cc16',
}
const DEFAULT_COLOR = '#6b7280'

const fmt = ts => format(new Date(ts), 'HH:mm:ss')
const fmtPrice = v => `$${Number(v).toFixed(2)}`

/* ── Overview chart (no symbol selected) ── */
function OverviewChart({ anomalies }) {
  const bySymbol = anomalies.reduce((acc, a) => {
    const key = a.symbol
    if (!acc[key]) acc[key] = []
    acc[key].push({ time: a.detected_at_ms, z: Math.abs(a.z_score), price: a.price, symbol: a.symbol })
    return acc
  }, {})

  const symbols = Object.keys(bySymbol)
  if (!symbols.length) return null

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-strong)',
        borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12,
      }}>
        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--blue)', marginBottom: 4 }}>{d.symbol}</div>
        <div style={{ color: 'var(--text-secondary)' }}>Time: {fmt(d.time)}</div>
        <div style={{ color: 'var(--text-primary)' }}>|Z| = <strong>{d.z.toFixed(3)}</strong></div>
        <div style={{ color: 'var(--text-secondary)' }}>Price: {fmtPrice(d.price)}</div>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ScatterChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="time" type="number" scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={fmt}
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          axisLine={{ stroke: 'var(--border)' }} tickLine={false}
        />
        <YAxis
          dataKey="z" name="|Z-Score|"
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          axisLine={{ stroke: 'var(--border)' }} tickLine={false}
          label={{ value: '|Z|', angle: -90, position: 'insideLeft', fill: 'var(--text-muted)', fontSize: 11 }}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, paddingTop: 8, fontFamily: 'var(--font-mono)' }}
          formatter={v => <span style={{ color: 'var(--text-secondary)' }}>{v}</span>}
        />
        <ReferenceLine y={3} stroke="var(--yellow)" strokeDasharray="4 4" label={{ value: 'threshold', fill: 'var(--yellow)', fontSize: 10 }} />
        {symbols.map(sym => (
          <Scatter
            key={sym} name={sym}
            data={bySymbol[sym]}
            fill={SYMBOL_COLORS[sym] || DEFAULT_COLOR}
            opacity={0.85}
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/* ── Symbol chart (symbol selected) ── */
function SymbolChart({ symbol, windowData, anomalies }) {
  const color = SYMBOL_COLORS[symbol] || DEFAULT_COLOR

  // Combine window price line with anomaly scatter points
  const lineData = windowData?.prices ?? []
  const anomalyPoints = anomalies.map(a => ({
    time: a.timestamp_ms,
    anomalyPrice: a.price,
    z: a.z_score,
  }))

  // Merge into a single dataset for ComposedChart
  // Line uses `price`, Scatter uses `anomalyPrice`
  const allTimes = new Set([
    ...lineData.map(p => p.time),
    ...anomalyPoints.map(p => p.time),
  ])
  const merged = Array.from(allTimes)
    .sort((a, b) => a - b)
    .map(time => {
      const lp = lineData.find(p => p.time === time)
      const ap = anomalyPoints.find(p => p.time === time)
      return { time, price: lp?.price, anomalyPrice: ap?.anomalyPrice, z: ap?.z }
    })

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    const price  = payload.find(p => p.dataKey === 'price')?.value
    const aPrice = payload.find(p => p.dataKey === 'anomalyPrice')?.value
    const z      = payload[0]?.payload?.z
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-strong)',
        borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12,
      }}>
        <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>{fmt(label)}</div>
        {price      != null && <div style={{ color: 'var(--text-secondary)' }}>Price: {fmtPrice(price)}</div>}
        {aPrice     != null && <div style={{ color: 'var(--red)' }}>⚠ Anomaly: {fmtPrice(aPrice)}</div>}
        {z          != null && <div style={{ color: 'var(--red)' }}>Z = {Number(z).toFixed(3)}</div>}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={merged} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="time" type="number" scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={fmt}
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          axisLine={{ stroke: 'var(--border)' }} tickLine={false}
        />
        <YAxis
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
          axisLine={{ stroke: 'var(--border)' }} tickLine={false}
          tickFormatter={v => `$${v.toFixed(0)}`}
          domain={['auto', 'auto']}
        />
        <Tooltip content={<CustomTooltip />} />
        <Line
          dataKey="price" type="monotone"
          stroke={color} strokeWidth={1.5}
          dot={false} connectNulls={false}
          name={`${symbol} price`}
        />
        <Scatter
          dataKey="anomalyPrice"
          fill="var(--red)" r={5}
          name="Anomaly"
          shape={<AnomalyDot />}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

function AnomalyDot({ cx, cy }) {
  if (cx == null || cy == null) return null
  return (
    <g>
      <circle cx={cx} cy={cy} r={5} fill="var(--red)" stroke="var(--bg-base)" strokeWidth={1.5} />
      <circle cx={cx} cy={cy} r={9} fill="none" stroke="var(--red)" strokeWidth={1} opacity={0.4} />
    </g>
  )
}

/* ── Public component ── */
export default function PriceChart({ selectedSymbol, anomalies, windowData }) {
  const title = selectedSymbol ? `${selectedSymbol} — Price & Anomalies` : 'Anomaly Z-Scores — All Symbols'

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">{title}</span>
        {selectedSymbol && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            ● price  ◎ anomaly
          </span>
        )}
      </div>
      <div className="chart-container">
        {!anomalies.length ? (
          <div className="chart-placeholder">
            <span style={{ fontSize: 28 }}>📊</span>
            <span>No data to chart yet</span>
          </div>
        ) : selectedSymbol ? (
          <SymbolChart symbol={selectedSymbol} windowData={windowData} anomalies={anomalies} />
        ) : (
          <OverviewChart anomalies={anomalies} />
        )}
      </div>
    </div>
  )
}

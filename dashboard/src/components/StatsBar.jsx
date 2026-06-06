import { useMemo } from 'react'

export default function StatsBar({ anomalies }) {
  const stats = useMemo(() => {
    if (!anomalies.length) return null

    const total = anomalies.length
    const avgZ  = anomalies.reduce((s, a) => s + Math.abs(a.z_score), 0) / total
    const maxZ  = Math.max(...anomalies.map(a => Math.abs(a.z_score)))

    const symbolCounts = {}
    for (const a of anomalies) symbolCounts[a.symbol] = (symbolCounts[a.symbol] || 0) + 1
    const topSymbol = Object.entries(symbolCounts).sort((x, y) => y[1] - x[1])[0]

    return { total, avgZ, maxZ, topSymbol }
  }, [anomalies])

  const cards = [
    {
      label: 'Anomalies',
      value: stats ? stats.total : '—',
      sub: 'last 24 hours',
    },
    {
      label: 'Top Symbol',
      value: stats ? stats.topSymbol[0] : '—',
      sub: stats ? `${stats.topSymbol[1]} events` : '',
    },
    {
      label: 'Avg |Z-Score|',
      value: stats ? stats.avgZ.toFixed(2) : '—',
      sub: 'across all events',
    },
    {
      label: 'Peak |Z-Score|',
      value: stats ? stats.maxZ.toFixed(2) : '—',
      sub: 'largest deviation',
      color: stats && stats.maxZ > 5 ? 'var(--red)' : stats && stats.maxZ > 4 ? 'var(--orange)' : 'var(--yellow)',
    },
  ]

  return (
    <div className="stats-bar">
      {cards.map(c => (
        <div key={c.label} className="stat-card">
          <div className="stat-label">{c.label}</div>
          <div className="stat-value" style={c.color ? { color: c.color } : {}}>
            {c.value}
          </div>
          <div className="stat-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  )
}

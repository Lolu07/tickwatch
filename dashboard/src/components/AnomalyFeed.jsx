import { useState, Fragment } from 'react'
import { format } from 'date-fns'

function zClass(z) {
  const abs = Math.abs(z)
  if (abs >= 5) return 'z-score z-extreme'
  if (abs >= 4) return 'z-score z-higher'
  return 'z-score z-high'
}

function zArrow(z) {
  return z > 0 ? '↑' : '↓'
}

export default function AnomalyFeed({ anomalies, newIds }) {
  const [expanded, setExpanded] = useState(new Set())

  const toggle = (id) => setExpanded(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  if (!anomalies.length) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">Anomaly Feed</span>
        </div>
        <div className="empty-state">
          <span className="empty-icon">📡</span>
          <p>No anomalies detected yet.</p>
          <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Run the ingestion service or synthetic producer to generate events.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Anomaly Feed</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {anomalies.length} event{anomalies.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="feed-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th className="right">Price</th>
              <th className="right">Z-Score</th>
              <th className="right">Mean</th>
              <th className="right">σ</th>
            </tr>
          </thead>
          <tbody>
            {anomalies.map(a => {
              const id = `${a.symbol}_${a.timestamp_ms}`
              const isNew = newIds.has(id)
              const hasExplanation = Boolean(a.explanation)
              const isExpanded = expanded.has(id)

              return (
                <Fragment key={id}>
                  <tr
                    className={`feed-row${isNew ? ' is-new' : ''}${hasExplanation ? ' has-explanation' : ''}`}
                    onClick={hasExplanation ? () => toggle(id) : undefined}
                  >
                    <td className="time-cell">
                      {hasExplanation && (
                        <span className="expand-toggle" aria-hidden="true">
                          {isExpanded ? '▾' : '▸'}
                        </span>
                      )}
                      {format(new Date(a.detected_at_ms), 'HH:mm:ss')}
                    </td>
                    <td>
                      <span className="symbol-badge">{a.symbol}</span>
                    </td>
                    <td className="right mono">${a.price.toFixed(4)}</td>
                    <td className="right">
                      <span className={zClass(a.z_score)}>
                        {zArrow(a.z_score)}{Math.abs(a.z_score).toFixed(2)}
                      </span>
                    </td>
                    <td className="right mono" style={{ color: 'var(--text-secondary)' }}>
                      {a.mean.toFixed(2)}
                    </td>
                    <td className="right mono" style={{ color: 'var(--text-secondary)' }}>
                      {a.stddev.toFixed(4)}
                    </td>
                  </tr>
                  {hasExplanation && isExpanded && (
                    <tr className="explanation-row">
                      <td colSpan={6}>
                        <div className="explanation-text">
                          <span className="explanation-icon">✦</span>
                          {a.explanation}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

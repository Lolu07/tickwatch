import { formatDistanceToNowStrict } from 'date-fns'

export default function Header({ lastUpdated, onRefresh }) {
  return (
    <header className="header">
      <div className="header-brand">
        <h1 className="header-logo">Tick<span>Watch</span></h1>
        <span className="live-badge">
          <span className="live-dot" />
          LIVE
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {lastUpdated && (
          <span className="header-meta">
            Updated {formatDistanceToNowStrict(lastUpdated, { addSuffix: true })}
          </span>
        )}
        <button
          onClick={onRefresh}
          style={{
            background: 'transparent',
            border: '1px solid var(--border-strong)',
            color: 'var(--text-secondary)',
            borderRadius: 'var(--radius-sm)',
            padding: '5px 12px',
            cursor: 'pointer',
            fontSize: 12,
            fontFamily: 'var(--font-sans)',
            transition: 'all var(--transition)',
          }}
          onMouseEnter={e => {
            e.target.style.borderColor = 'var(--blue)'
            e.target.style.color = 'var(--blue)'
          }}
          onMouseLeave={e => {
            e.target.style.borderColor = 'var(--border-strong)'
            e.target.style.color = 'var(--text-secondary)'
          }}
        >
          ↺ Refresh
        </button>
      </div>
    </header>
  )
}

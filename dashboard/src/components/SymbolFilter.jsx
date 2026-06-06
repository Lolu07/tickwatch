export default function SymbolFilter({ symbols, selected, onChange }) {
  const all = ['All', ...symbols]

  return (
    <div className="symbol-filter">
      {all.map(sym => (
        <button
          key={sym}
          className={`symbol-chip ${(selected === null ? 'All' : selected) === sym ? 'active' : ''}`}
          onClick={() => onChange(sym === 'All' ? null : sym)}
        >
          {sym}
        </button>
      ))}
    </div>
  )
}

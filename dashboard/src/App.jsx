import { useState } from 'react'
import Header from './components/Header.jsx'
import StatsBar from './components/StatsBar.jsx'
import SymbolFilter from './components/SymbolFilter.jsx'
import AnomalyFeed from './components/AnomalyFeed.jsx'
import PriceChart from './components/PriceChart.jsx'
import { useAnomalies } from './hooks/useAnomalies.js'

export default function App() {
  const [selectedSymbol, setSelectedSymbol] = useState(null)

  const {
    anomalies, symbols, windowData,
    newIds, loading, error, lastUpdated, refresh,
  } = useAnomalies(selectedSymbol)

  const filteredAnomalies = selectedSymbol
    ? anomalies.filter(a => a.symbol === selectedSymbol)
    : anomalies

  return (
    <div className="app">
      <Header lastUpdated={lastUpdated} onRefresh={refresh} />

      {loading && <div className="loading-bar" />}

      {error && (
        <div className="error-banner">
          ⚠ Could not reach API: {error}
          {!import.meta.env.VITE_API_URL && (
            <span> — set <code>VITE_API_URL</code> in <code>dashboard/.env.local</code></span>
          )}
        </div>
      )}

      <StatsBar anomalies={anomalies} />

      <SymbolFilter
        symbols={symbols}
        selected={selectedSymbol}
        onChange={setSelectedSymbol}
      />

      <div className="main-content">
        <AnomalyFeed anomalies={filteredAnomalies} newIds={newIds} />

        <PriceChart
          selectedSymbol={selectedSymbol}
          anomalies={filteredAnomalies}
          windowData={windowData}
        />
      </div>
    </div>
  )
}

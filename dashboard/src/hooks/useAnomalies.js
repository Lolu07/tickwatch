import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchAnomalies, fetchSymbols, fetchWindow } from '../api/client.js'

const POLL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 15_000

/**
 * Central data hook — polls the API and drives the entire dashboard.
 *
 * Returns:
 *   anomalies    — current list sorted newest-first
 *   symbols      — all available ticker symbols
 *   windowData   — { symbol, prices: [{time, price}], updated_at }
 *   newIds       — Set of `${symbol}_${timestamp_ms}` keys added in the
 *                  last refresh (used to animate new rows in AnomalyFeed)
 *   loading      — true only on the very first fetch
 *   error        — error message string or null
 *   lastUpdated  — Date of the most recent successful fetch
 *   refresh      — call to force an immediate refresh
 */
export function useAnomalies(selectedSymbol) {
  const [anomalies, setAnomalies]   = useState([])
  const [symbols, setSymbols]       = useState([])
  const [windowData, setWindowData] = useState(null)
  const [newIds, setNewIds]         = useState(new Set())
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const prevIdsRef = useRef(new Set())
  const timerRef   = useRef(null)

  const fetchAll = useCallback(async () => {
    try {
      const [fresh] = await fetchAnomalies({ symbol: selectedSymbol, limit: 100 })

      // Detect which IDs are new since the last poll
      const freshIds = new Set(fresh.map(a => `${a.symbol}_${a.timestamp_ms}`))
      const added = new Set([...freshIds].filter(id => !prevIdsRef.current.has(id)))
      prevIdsRef.current = freshIds

      setAnomalies(fresh)
      setNewIds(added)
      setError(null)
      setLastUpdated(new Date())
      // Clear "new" highlights after 3 s
      setTimeout(() => setNewIds(new Set()), 3000)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [selectedSymbol])

  const fetchSymbolList = useCallback(async () => {
    try {
      const list = await fetchSymbols()
      setSymbols(list)
    } catch {
      // Non-fatal — symbols list is cosmetic
    }
  }, [])

  const fetchChartData = useCallback(async () => {
    if (!selectedSymbol) {
      setWindowData(null)
      return
    }
    try {
      const [data] = await fetchWindow(selectedSymbol)
      setWindowData(data)
    } catch {
      setWindowData(null)
    }
  }, [selectedSymbol])

  const refresh = useCallback(() => {
    fetchAll()
    fetchChartData()
  }, [fetchAll, fetchChartData])

  // Initial load
  useEffect(() => {
    fetchAll()
    fetchSymbolList()
    fetchChartData()
  }, [fetchAll, fetchSymbolList, fetchChartData])

  // Polling
  useEffect(() => {
    timerRef.current = setInterval(refresh, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [refresh])

  return { anomalies, symbols, windowData, newIds, loading, error, lastUpdated, refresh }
}

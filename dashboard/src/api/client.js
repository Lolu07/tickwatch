/**
 * API client — all calls to the API Gateway go through here.
 *
 * The response envelope from the Lambda is:
 *   { data: { ... }, meta: { query_ms, count, version } }
 *
 * Callers receive the unwrapped `data` object; `meta` is available via
 * the second element of the returned tuple if needed.
 */

const BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

async function get(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null)
  ).toString()
  const url = `${BASE_URL}${path}${qs ? `?${qs}` : ''}`

  const resp = await fetch(url, {
    headers: { Accept: 'application/json' },
  })

  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`API ${resp.status}: ${text || resp.statusText}`)
  }

  const envelope = await resp.json()
  return [envelope.data, envelope.meta]
}

/** Fetch recent anomalies, optionally filtered to one symbol. */
export async function fetchAnomalies({ symbol, limit } = {}) {
  if (symbol) {
    const [data, meta] = await get(`/anomalies/${symbol}`, { limit })
    return [data.anomalies ?? [], meta]
  }
  const [data, meta] = await get('/anomalies', { limit })
  return [data.anomalies ?? [], meta]
}

/** Fetch the rolling price window for a symbol (used for the chart). */
export async function fetchWindow(symbol) {
  const [data, meta] = await get(`/windows/${encodeURIComponent(symbol)}`)
  return [data, meta]
}

/** Fetch the list of symbols that have data. */
export async function fetchSymbols() {
  const [data] = await get('/symbols')
  return data.symbols ?? []
}

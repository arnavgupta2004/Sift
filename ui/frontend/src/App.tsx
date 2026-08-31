import { useEffect, useRef, useState } from 'react'
import './App.css'
import { getPersonalization, listUsers } from './api'
import { streamQuery } from './api'
import { BaselineChart } from './components/BaselineChart'
import { PersonalizationPanel } from './components/PersonalizationPanel'
import { ResultsList } from './components/ResultsList'
import { TracePanel } from './components/TracePanel'
import type { PersonalizationInsights, ResultItem, RoutingTraceData, StageTrace, UserSummary } from './types'

const EXAMPLE_QUERIES = [
  'open q3_revenue_report.xlsx',
  'find my recent notes about transformers',
  "find that thing I was working on with my advisor about audio deepfakes a few weeks ago",
]

function App() {
  const [users, setUsers] = useState<UserSummary[]>([])
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [query, setQuery] = useState(EXAMPLE_QUERIES[2])

  const [tier, setTier] = useState<string | null>(null)
  const [rationale, setRationale] = useState('')
  const [stagesByName, setStagesByName] = useState<Record<string, StageTrace>>({})
  const [results, setResults] = useState<ResultItem[]>([])
  const [finalTrace, setFinalTrace] = useState<RoutingTraceData | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [lastQuery, setLastQuery] = useState('')

  const [insights, setInsights] = useState<PersonalizationInsights | null>(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  const cancelRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    listUsers()
      .then((u) => {
        setUsers(u)
        if (u.length > 0) setSelectedUserId(u[0].id)
      })
      .catch(() => setApiError('Cannot reach the API. Is `uvicorn app.api:app` running on :8000?'))
  }, [])

  useEffect(() => {
    if (selectedUserId === null) return
    setInsightsLoading(true)
    getPersonalization(selectedUserId)
      .then(setInsights)
      .catch(() => setInsights(null))
      .finally(() => setInsightsLoading(false))
  }, [selectedUserId, results])

  function runQuery() {
    if (selectedUserId === null || !query.trim()) return
    cancelRef.current?.()

    setTier(null)
    setRationale('')
    setStagesByName({})
    setResults([])
    setFinalTrace(null)
    setIsStreaming(true)
    setLastQuery(query)
    setApiError(null)

    cancelRef.current = streamQuery(
      query,
      selectedUserId,
      (event) => {
        if (event.type === 'route') {
          setTier(event.tier)
          setRationale(event.rationale)
        } else if (event.type === 'stage') {
          setStagesByName((prev) => ({
            ...prev,
            [event.name]: { name: event.name, duration_ms: event.duration_ms, skipped: event.skipped, detail: event.detail },
          }))
        } else if (event.type === 'done') {
          setResults(event.results)
          setFinalTrace(event.routing_trace)
          setIsStreaming(false)
        }
      },
      () => {
        setIsStreaming(false)
        setApiError('Query stream failed — check that the API is still running.')
      },
    )
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Sift</h1>
        <p className="app-subtitle">Agentic file recommendation and retrieval — live routing, personalized, explained.</p>
      </header>

      {apiError && <div className="error-banner">{apiError}</div>}

      <div className="query-bar panel">
        <select
          value={selectedUserId ?? ''}
          onChange={(e) => setSelectedUserId(Number(e.target.value))}
          className="user-select"
        >
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.persona_key})
            </option>
          ))}
        </select>
        <input
          className="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runQuery()}
          placeholder="Search your files…"
        />
        <button className="run-button" onClick={runQuery} disabled={isStreaming}>
          {isStreaming ? 'Running…' : 'Search'}
        </button>
      </div>

      <div className="example-queries">
        {EXAMPLE_QUERIES.map((q) => (
          <button key={q} className="example-chip" onClick={() => setQuery(q)}>
            {q}
          </button>
        ))}
      </div>

      <div className="main-grid">
        <div className="main-column">
          <TracePanel
            tier={tier}
            rationale={rationale}
            stagesByName={stagesByName}
            isStreaming={isStreaming}
            finalTrace={finalTrace}
          />

          <div className="panel">
            <h3>Results {results.length > 0 && `(${results.length})`}</h3>
            <ResultsList results={results} userId={selectedUserId ?? 0} query={lastQuery} />
          </div>

          <BaselineChart />
        </div>

        <div className="side-column">
          <PersonalizationPanel insights={insights} loading={insightsLoading} />
        </div>
      </div>
    </div>
  )
}

export default App

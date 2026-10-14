import { useEffect, useRef, useState } from 'react'
import './App.css'
import { getMe, getPersonalization, searchImages } from './api'
import { streamQuery } from './api'
import { ImageResults } from './components/ImageResults'
import { IndexStatus } from './components/IndexStatus'
import { PersonalizationPanel } from './components/PersonalizationPanel'
import { ResultsList } from './components/ResultsList'
import { TracePanel } from './components/TracePanel'
import { Logo } from './components/Logo'
import { Spotlight } from './spotlight/Spotlight'
import type { ImageHit, PersonalizationInsights, ResultItem, RoutingTraceData, StageTrace, UserSummary } from './types'

// Shortcut hints use the keys printed on this keyboard.
const MOD_KEY = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : 'Ctrl '

const EXAMPLE_QUERIES = [
  'Find my latest presentation',
  'Show spreadsheets I used recently',
  'Find the notes about my project from last week',
]

type Mode = 'files' | 'images'

// How this window was launched. The system-wide shortcut opens `/quick-search` in a small
// app window that shows only the quick search; `?q=` (and `&mode=images`) runs a search
// on load, which is how the quick search hands over to this full page.
const launch = new URLSearchParams(window.location.search)
const STANDALONE = window.location.pathname === '/quick-search' || launch.has('spotlight')
const INITIAL_QUERY = launch.get('q') ?? ''
const INITIAL_MODE: Mode = launch.get('mode') === 'images' ? 'images' : 'files'

function closeSpotlightWindow() {
  window.close()
  // Browsers only let a page close a window they opened themselves; if this one stays
  // open, turn it into the full app instead of leaving an empty frame behind.
  window.setTimeout(() => window.location.assign('/'), 150)
}

const EXAMPLE_IMAGE_QUERIES = ['a person smiling', 'a screenshot of code', 'a whiteboard with equations']

function App() {
  const [mode, setMode] = useState<Mode>(INITIAL_MODE)
  const [imageHits, setImageHits] = useState<ImageHit[]>([])
  const [imagesSearched, setImagesSearched] = useState(false)
  const [me, setMe] = useState<UserSummary | null>(null)
  const [query, setQuery] = useState(INITIAL_QUERY)

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
  const [spotlightOpen, setSpotlightOpen] = useState(false)
  const [insightsVersion, setInsightsVersion] = useState(0)
  const ranInitialQuery = useRef(false)

  // The server may still be starting (the shortcut starts it on demand), so keep asking.
  useEffect(() => {
    let timer: number | undefined
    let tries = 0
    function ask() {
      getMe()
        .then((user) => {
          setMe(user)
          setApiError(null)
        })
        .catch(() => {
          tries++
          if (tries === 3) setApiError('Sift cannot connect right now. Please make sure the Sift service is running.')
          timer = window.setTimeout(ask, 2000)
        })
    }
    ask()
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (me === null) return
    setInsightsLoading(true)
    getPersonalization(me.id)
      .then(setInsights)
      .catch(() => setInsights(null))
      .finally(() => setInsightsLoading(false))
  }, [me, results, insightsVersion])

  // ⌘K / Ctrl+K opens the Spotlight-style quick search over this page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSpotlightOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function showInFullView(q: string, m: Mode) {
    if (STANDALONE) {
      window.open(`/?${new URLSearchParams({ q, mode: m })}`, '_blank')
      closeSpotlightWindow()
      return
    }
    setSpotlightOpen(false)
    setMode(m)
    setQuery(q)
    search(q, m)
  }

  function runImageQuery(query: string) {
    if (!query.trim()) return
    setIsStreaming(true)
    setApiError(null)
    setLastQuery(query)
    searchImages(query)
      .then((hits) => {
        setImageHits(hits)
        setImagesSearched(true)
      })
      .catch(() => setApiError('Image search failed — check that the Sift service is running.'))
      .finally(() => setIsStreaming(false))
  }

  function runQuery() {
    search(query, mode)
  }

  function search(query: string, mode: Mode) {
    if (mode === 'images') return runImageQuery(query)
    if (me === null || !query.trim()) return
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
      me.id,
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

  // A search passed in the address (?q=) runs once the user is known.
  useEffect(() => {
    if (STANDALONE || me === null || !INITIAL_QUERY || ranInitialQuery.current) return
    ranInitialQuery.current = true
    window.history.replaceState(null, '', '/')
    search(INITIAL_QUERY, INITIAL_MODE)
  })

  if (STANDALONE) {
    return (
      <Spotlight
        standalone
        me={me}
        insights={insights}
        insightsLoading={insightsLoading}
        onOpened={() => setInsightsVersion((v) => v + 1)}
        onClose={closeSpotlightWindow}
        onShowInFull={showInFullView}
      />
    )
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-mark"><Logo size={26} /></div>
        <div>
          <h1>Sift</h1>
          <p className="app-subtitle">Find the right file, even when you only remember part of it.</p>
        </div>
        <button className="spotlight-launch" onClick={() => setSpotlightOpen(true)} title="Quick search (⌘K / Ctrl+K)">
          Quick search <kbd>{MOD_KEY}K</kbd>
        </button>
      </header>

      {apiError && <div className="error-banner">{apiError}</div>}

      <section className="search-hero">
        <div className="search-copy">
          <h2>What are you looking for?</h2>
          <p>Use everyday words. Try a name, topic, file type, or when you last used it.</p>
        </div>
        <div className="mode-switch" role="tablist" aria-label="What to search">
          {(['files', 'images'] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? 'active' : ''} onClick={() => setMode(m)}>
              {m === 'files' ? 'Files' : 'Images'}
            </button>
          ))}
        </div>
        <div className="query-bar">
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></svg>
          <input
            className="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runQuery()}
            placeholder={mode === 'files' ? 'e.g. the budget spreadsheet I opened last month' : 'Describe the picture, e.g. a dog on a couch'}
            aria-label="Describe the file you want to find"
          />
          <button className="run-button" onClick={runQuery} disabled={isStreaming || !query.trim() || (mode === 'files' && me === null)}>
            {isStreaming ? 'Searching…' : mode === 'files' ? 'Find files' : 'Find images'}
          </button>
        </div>
        <div className="example-area">
          <span>Try:</span>
          {(mode === 'files' ? EXAMPLE_QUERIES : EXAMPLE_IMAGE_QUERIES).map((q) => (
            <button key={q} className="example-chip" onClick={() => setQuery(q)}>
              {q}
            </button>
          ))}
        </div>
        <div className="search-options">
          <IndexStatus />
          <span className="privacy-note">Your files stay on this device.</span>
        </div>
      </section>

      <div className="main-grid">
        <main className="main-column">
          {mode === 'images' ? (
            <section className="results-panel panel" aria-live="polite">
              <div className="results-heading">
                <div>
                  <h2>{isStreaming ? 'Looking through your pictures…' : imageHits.length ? 'Matching images' : 'Describe a picture'}</h2>
                  <p>{lastQuery && imagesSearched && !isStreaming ? `Images matching “${lastQuery}”` : 'Sift compares your words to what is in each image, not its file name.'}</p>
                </div>
                {imageHits.length > 0 && <span className="results-count">{imageHits.length} {imageHits.length === 1 ? 'image' : 'images'}</span>}
              </div>
              <ImageResults hits={imageHits} userId={me?.id ?? 0} searched={imagesSearched} />
            </section>
          ) : (
          <section className="results-panel panel" aria-live="polite">
            <div className="results-heading">
              <div>
                <h2>{isStreaming ? 'Looking through your files…' : results.length ? 'Recommended files' : 'Your recommendations will appear here'}</h2>
                <p>{lastQuery && !isStreaming ? `Results for “${lastQuery}”` : 'Search by what you remember — Sift handles the rest.'}</p>
              </div>
              {results.length > 0 && <span className="results-count">{results.length} {results.length === 1 ? 'match' : 'matches'}</span>}
            </div>
            <ResultsList results={results} userId={me?.id ?? 0} query={lastQuery} />
          </section>
          )}

          {mode === 'files' && (tier || finalTrace) && (
            <details className="advanced-details">
              <summary>How Sift searched</summary>
              <p>This is the technical search path used for this request.</p>
              <TracePanel
                tier={tier}
                rationale={rationale}
                stagesByName={stagesByName}
                isStreaming={isStreaming}
                finalTrace={finalTrace}
              />
            </details>
          )}
        </main>

        <aside className="side-column">
          <PersonalizationPanel insights={insights} loading={insightsLoading} />
        </aside>
      </div>

      {spotlightOpen && (
        <Spotlight
          me={me}
          insights={insights}
          insightsLoading={insightsLoading}
          onOpened={() => setInsightsVersion((v) => v + 1)}
          onClose={() => setSpotlightOpen(false)}
          onShowInFull={showInFullView}
        />
      )}
    </div>
  )
}

export default App

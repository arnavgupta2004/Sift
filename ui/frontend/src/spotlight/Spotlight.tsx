import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './Spotlight.css'
import { openFile, searchImages, streamQuery } from '../api'
import { IndexStatus } from '../components/IndexStatus'
import { PersonalizationPanel } from '../components/PersonalizationPanel'
import { Logo } from '../components/Logo'
import type { ImageHit, PersonalizationInsights, ResultItem, UserSummary } from '../types'
import { Preview } from './Preview'
import { SpotlightImages } from './SpotlightImages'
import { SpotlightList, type Row } from './SpotlightList'

const EXAMPLE_QUERIES = ['Find my latest presentation', 'Spreadsheets I used recently', 'Notes about my project from last week']
const EXAMPLE_IMAGE_QUERIES = ['a person smiling', 'a screenshot of code', 'a whiteboard with equations']

// Search as you type, Spotlight-style: wait for a short pause in typing first, since
// every search runs the retrieval pipeline. Enter searches immediately.
const MOD_KEY = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : 'Ctrl '
const TYPING_PAUSE_MS = 300
const MAX_RESULTS = 5

export type Mode = 'files' | 'images'

interface Props {
  /** The whole window is the quick search (opened by the system-wide shortcut). */
  standalone?: boolean
  me: UserSummary | null
  insights: PersonalizationInsights | null
  insightsLoading: boolean
  onOpened: () => void
  onClose: () => void
  /** Hands the current search over to the full page (like Spotlight's "Search in Finder"). */
  onShowInFull: (query: string, mode: Mode) => void
}

/** The ⌘K pop-up search, drawn over the main page. */
export function Spotlight({ standalone = false, me, insights, insightsLoading, onOpened, onClose, onShowInFull }: Props) {
  const [mode, setMode] = useState<Mode>('files')
  const [query, setQuery] = useState('')
  const [searchedQuery, setSearchedQuery] = useState('')
  const [selected, setSelected] = useState(0)

  const [results, setResults] = useState<ResultItem[]>([])
  const [imageHits, setImageHits] = useState<ImageHit[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  const imageRequestRef = useRef(0)

  useEffect(() => () => cancelRef.current?.(), [])

  const runSearch = useCallback(
    (q: string) => {
      cancelRef.current?.()
      cancelRef.current = null
      setSearchedQuery(q)
      setSelected(0)
      setError(null)
      if (!q) {
        setResults([])
        setImageHits([])
        setIsSearching(false)
        return
      }
      setIsSearching(true)

      if (mode === 'images') {
        const request = ++imageRequestRef.current
        searchImages(q)
          .then((hits) => request === imageRequestRef.current && setImageHits(hits))
          .catch(() => setError('Image search failed. Check that the Sift service is running.'))
          .finally(() => request === imageRequestRef.current && setIsSearching(false))
        return
      }

      if (me === null) {
        // Not connected yet: say so rather than spinning. The search re-runs once connected.
        setIsSearching(false)
        setSearchedQuery('')
        setError('Sift is still starting. Your search will run in a moment.')
        return
      }
      cancelRef.current = streamQuery(
        q,
        me.id,
        (event) => {
          if (event.type === 'done') {
            setResults(event.results.slice(0, MAX_RESULTS))
            setIsSearching(false)
          }
        },
        () => {
          setIsSearching(false)
          setError('Search failed. Check that the Sift service is still running.')
        },
      )
    },
    [me, mode],
  )

  // Search as you type.
  useEffect(() => {
    const q = query.trim()
    if (q === searchedQuery) return
    const timer = window.setTimeout(() => runSearch(q), q ? TYPING_PAUSE_MS : 0)
    return () => window.clearTimeout(timer)
  }, [query, searchedQuery, runSearch])

  const rows: Row[] = useMemo(() => {
    if (searchedQuery) {
      return results.map((r, i) => ({
        file_id: r.file_id,
        filename: r.filename,
        path: r.path,
        file_type: r.file_type,
        section: i === 0 ? 'Top Hit' : 'Files',
        result: r,
      }))
    }
    return (insights?.suggested_files ?? []).map((f) => ({
      file_id: f.file_id,
      filename: f.filename,
      path: f.path,
      file_type: f.file_type,
      section: f.reason === 'usual_now' ? 'Usually open around now' : 'Recently opened',
      note: f.reason === 'usual_now' ? 'You tend to open this at this time of the week' : undefined,
    }))
  }, [searchedQuery, results, insights])

  const count = mode === 'images' ? imageHits.length : rows.length
  const selectedRow = mode === 'files' ? rows[Math.min(selected, rows.length - 1)] : undefined

  // Switching between Files and Images re-runs the current text in the new mode.
  function switchMode(m: Mode) {
    setMode(m)
    setSearchedQuery('')
    setResults([])
    setImageHits([])
    setSelected(0)
    inputRef.current?.focus()
  }

  async function open(fileId: number) {
    if (me === null) return
    try {
      setError(null)
      await openFile(fileId, me.id, searchedQuery)
      onOpened()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open the file')
    }
  }

  function onInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (count) setSelected((s) => (s + (e.key === 'ArrowDown' ? 1 : count - 1)) % count)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const q = query.trim()
      if ((e.metaKey || e.ctrlKey) && q) onShowInFull(q, mode)
      else if (q !== searchedQuery) runSearch(q)
      else if (mode === 'images' && imageHits[selected]) open(imageHits[selected].file_id)
      else if (selectedRow) open(selectedRow.file_id)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      if (query) setQuery('')
      else onClose()
    }
  }

  const examples = mode === 'files' ? EXAMPLE_QUERIES : EXAMPLE_IMAGE_QUERIES
  const nothingFound = !!searchedQuery && !isSearching && count === 0

  return (
    <div className={standalone ? 'spotlight-overlay standalone' : 'spotlight-overlay'} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="spotlight" role="dialog" aria-modal="true" aria-label="Quick search">
        <div className="sl-bar">
          <span className="sl-mark"><Logo size={22} /></span>
          <input
            ref={inputRef}
            autoFocus
            className="sl-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKey}
            placeholder={mode === 'files' ? 'Sift Search' : 'Describe a picture'}
            aria-label={mode === 'files' ? 'Describe the file you want' : 'Describe the picture you want'}
            role="combobox"
            aria-expanded={count > 0}
            spellCheck={false}
          />
          {isSearching && <span className="sl-spinner" aria-label="Searching" />}
          <div className="sl-mode" role="tablist" aria-label="What to search">
            {(['files', 'images'] as const).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? 'active' : ''} onClick={() => switchMode(m)}>
                {m === 'files' ? 'Files' : 'Images'}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="sl-banner error">{error}</div>}

        <div className="sl-body">
          {mode === 'images' ? (
            imageHits.length > 0 ? (
              <SpotlightImages hits={imageHits} selected={selected} onSelect={setSelected} onOpen={(h) => open(h.file_id)} />
            ) : (
              <EmptyState
                text={nothingFound ? 'No images matched. Images are matched by what is in them, so try other words.' : 'Describe what is in the picture. Sift looks at the image itself, not its name.'}
                examples={nothingFound ? [] : examples}
                onPick={setQuery}
              />
            )
          ) : rows.length > 0 ? (
            <div className="sl-split">
              <SpotlightList rows={rows} selected={selected} onSelect={setSelected} onOpen={(r) => open(r.file_id)} />
              {searchedQuery && selectedRow ? (
                <Preview row={selectedRow} userId={me?.id ?? 0} query={searchedQuery} onOpen={(r) => open(r.file_id)} />
              ) : (
                <div className="sl-preview">
                  <PersonalizationPanel insights={insights} loading={insightsLoading} />
                </div>
              )}
            </div>
          ) : isSearching ? (
            <p className="sl-empty">Searching your files…</p>
          ) : (
            <EmptyState
              text={nothingFound ? `No files matched “${searchedQuery}”.` : 'Search by name, topic, file type, or when you last used it.'}
              examples={nothingFound ? [] : examples}
              onPick={setQuery}
            />
          )}
        </div>

        <footer className="sl-footer">
          <IndexStatus />
          <div className="sl-hints">
            {query.trim() && (
              <button className="sl-link" onClick={() => onShowInFull(query.trim(), mode)}>
                Show in full view <kbd>{MOD_KEY}↵</kbd>
              </button>
            )}
            <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
            <span><kbd>↵</kbd> open</span>
            <span><kbd>esc</kbd> close</span>
          </div>
        </footer>
      </div>
    </div>
  )
}

function EmptyState({ text, examples, onPick }: { text: string; examples: string[]; onPick: (q: string) => void }) {
  return (
    <div className="sl-empty">
      <p>{text}</p>
      {examples.length > 0 && (
        <div className="sl-examples">
          {examples.map((q) => (
            <button key={q} className="sl-chip" onClick={() => onPick(q)}>{q}</button>
          ))}
        </div>
      )}
    </div>
  )
}

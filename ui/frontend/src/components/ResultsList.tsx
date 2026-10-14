import { useState } from 'react'
import type { ResultItem } from '../types'
import { openFile, sendFeedback } from '../api'
import { MATCH_LABELS, folderOf, matchLevel, timeAgo, tidyPath } from '../format'
import { FileIcon } from './FileIcon'

interface Props {
  results: ResultItem[]
  userId: number
  query: string
}

export function ResultsList({ results, userId, query }: Props) {
  const [openError, setOpenError] = useState<string | null>(null)
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, 'thumbs_up' | 'thumbs_down'>>({})

  async function handleFeedback(fileId: number, signal: 'thumbs_up' | 'thumbs_down') {
    setFeedbackGiven((prev) => ({ ...prev, [fileId]: signal }))
    await sendFeedback(userId, fileId, query, signal)
  }

  async function handleOpen(fileId: number) {
    try {
      setOpenError(null)
      await openFile(fileId, userId, query)
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Could not open the file')
    }
  }

  if (results.length === 0) {
    return <p className="empty-state">Start with a search above. Your best matches will show up here.</p>
  }

  return (
    <div className="results-list">
      {openError && <div className="error-banner">{openError}</div>}
      {results.map((r) => {
        const level = matchLevel(r.confidence)
        const pct = Math.round(r.confidence * 100)
        const opened = timeAgo(r.last_opened)
        return (
          <div className="result-card" key={r.file_id}>
            <FileIcon fileType={r.file_type} size={30} />
            <div className="result-main">
              <div className="result-title-row">
                <button className="result-filename result-open" onClick={() => handleOpen(r.file_id)} title={`Open ${r.path}`}>
                  {r.filename}
                </button>
                <span className="result-topic">{r.topic_cluster}</span>
              </div>
              <div className="result-meta">
                <span className="result-path" title={r.path}>{tidyPath(folderOf(r.path))}</span>
                <span>Modified {timeAgo(r.modified_at)}</span>
                {opened && <span className="result-opened">You opened it {opened}</span>}
              </div>
              <details className="result-why">
                <summary>Why this result</summary>
                <p className="result-why-detail">{r.explanation}</p>
              </details>
            </div>
            <div className="result-side">
              <div className={`result-match conf-${level}`} title="How strongly this stands out from the other candidates">
                <span className="result-score-value">{pct}%</span>
                <span className="result-score-label">{MATCH_LABELS[level]}</span>
                <div className="result-score-bar-track">
                  <div className="result-score-bar-fill" style={{ width: `${pct}%` }} />
                </div>
              </div>
              <div className="feedback-buttons">
                <button
                  className={feedbackGiven[r.file_id] === 'thumbs_up' ? 'feedback-btn active' : 'feedback-btn'}
                  onClick={() => handleFeedback(r.file_id, 'thumbs_up')}
                  aria-label="Right file"
                  title="Right file"
                >
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 9v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4.5-7a1.8 1.8 0 0 1 3.2 1.5L13.5 8H16a2 2 0 0 1 2 2.3l-1.1 6.5A2 2 0 0 1 14.9 18H9a2 2 0 0 1-2-2V9Z" />
                  </svg>
                </button>
                <button
                  className={feedbackGiven[r.file_id] === 'thumbs_down' ? 'feedback-btn active' : 'feedback-btn'}
                  onClick={() => handleFeedback(r.file_id, 'thumbs_down')}
                  aria-label="Wrong file"
                  title="Wrong file"
                >
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M13 11V2h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3Zm0 0-4.5 7a1.8 1.8 0 0 1-3.2-1.5L6.5 12H4a2 2 0 0 1-2-2.3l1.1-6.5A2 2 0 0 1 5.1 2H11a2 2 0 0 1 2 2v7Z" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

import { useState } from 'react'
import type { ResultItem } from '../types'
import { sendFeedback } from '../api'

interface Props {
  results: ResultItem[]
  userId: number
  query: string
}

export function ResultsList({ results, userId, query }: Props) {
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, 'thumbs_up' | 'thumbs_down'>>({})

  async function handleFeedback(fileId: number, signal: 'thumbs_up' | 'thumbs_down') {
    setFeedbackGiven((prev) => ({ ...prev, [fileId]: signal }))
    await sendFeedback(userId, fileId, query, signal)
  }

  if (results.length === 0) {
    return <p className="empty-state">No results yet — run a query.</p>
  }

  return (
    <div className="results-list">
      {results.map((r) => (
        <div className="result-card" key={r.file_id}>
          <div className="result-main">
            <div className="result-title-row">
              <span className="result-filename">{r.filename}</span>
              <span className="result-filetype">{r.file_type}</span>
              <span className="result-topic">{r.topic_cluster}</span>
            </div>
            <p className="result-explanation">{r.explanation}</p>
            <div className="result-score-bar-track">
              <div className="result-score-bar-fill" style={{ width: `${Math.min(100, r.score * 100)}%` }} />
            </div>
          </div>
          <div className="result-side">
            <span className="result-score-value">{r.score.toFixed(3)}</span>
            <div className="feedback-buttons">
              <button
                className={feedbackGiven[r.file_id] === 'thumbs_up' ? 'feedback-btn active' : 'feedback-btn'}
                onClick={() => handleFeedback(r.file_id, 'thumbs_up')}
                aria-label="thumbs up"
              >
                👍
              </button>
              <button
                className={feedbackGiven[r.file_id] === 'thumbs_down' ? 'feedback-btn active' : 'feedback-btn'}
                onClick={() => handleFeedback(r.file_id, 'thumbs_down')}
                aria-label="thumbs down"
              >
                👎
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

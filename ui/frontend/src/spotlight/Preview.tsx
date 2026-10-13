import { useState } from 'react'
import { sendFeedback } from '../api'
import { MATCH_LABELS, matchLevel, timeAgo, tidyPath } from '../format'
import { FileIcon } from '../components/FileIcon'
import type { Row } from './SpotlightList'

interface Props {
  row: Row
  userId: number
  query: string
  onOpen: (row: Row) => void
}

export function Preview({ row, userId, query, onOpen }: Props) {
  const [feedback, setFeedback] = useState<Record<number, 'thumbs_up' | 'thumbs_down'>>({})
  const r = row.result

  async function rate(signal: 'thumbs_up' | 'thumbs_down') {
    setFeedback((prev) => ({ ...prev, [row.file_id]: signal }))
    await sendFeedback(userId, row.file_id, query, signal)
  }

  const facts: [string, string][] = [['Kind', row.file_type.toUpperCase()]]
  if (r) facts.push(['Modified', timeAgo(r.modified_at) ?? '—'])
  if (r?.last_opened) facts.push(['Last opened', timeAgo(r.last_opened) ?? '—'])
  if (r && r.open_count > 0) facts.push(['Opened', `${r.open_count} time${r.open_count === 1 ? '' : 's'}`])
  // Zero-width breaks after each slash: long paths wrap between folders, not mid-name.
  facts.push(['Where', tidyPath(row.path).replace(/\//g, '/\u200b')])

  const level = r ? matchLevel(r.confidence) : null

  return (
    <div className="sl-preview">
      <div className="sl-preview-hero">
        <FileIcon fileType={row.file_type} size={52} />
        <h3>{row.filename}</h3>
        {r && level && (
          <div className={`sl-meter conf-${level}`}>
            <div className="sl-meter-track"><span style={{ width: `${Math.round(r.confidence * 100)}%` }} /></div>
            <span>{MATCH_LABELS[level]} · {Math.round(r.confidence * 100)}%</span>
          </div>
        )}
        {row.note && <p className="sl-preview-note">{row.note}</p>}
      </div>

      <dl className="sl-facts">
        {facts.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd title={v}>{v}</dd>
          </div>
        ))}
      </dl>

      {r && r.open_count > 0 && <p className="sl-personal">You've opened this before, so Sift ranks it higher.</p>}

      <div className="sl-actions">
        <button className="sl-open" onClick={() => onOpen(row)}>Open <kbd>↵</kbd></button>
        {r && (
          <div className="feedback-buttons">
            {(['thumbs_up', 'thumbs_down'] as const).map((signal) => (
              <button
                key={signal}
                className={feedback[row.file_id] === signal ? 'feedback-btn active' : 'feedback-btn'}
                onClick={() => rate(signal)}
                aria-label={signal === 'thumbs_up' ? 'Right file' : 'Wrong file'}
                title={signal === 'thumbs_up' ? 'Right file' : 'Wrong file'}
              >
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
                  style={signal === 'thumbs_down' ? { transform: 'rotate(180deg)' } : undefined}>
                  <path d="M7 9v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4.5-7a1.8 1.8 0 0 1 3.2 1.5L13.5 8H16a2 2 0 0 1 2 2.3l-1.1 6.5A2 2 0 0 1 14.9 18H9a2 2 0 0 1-2-2V9Z" />
                </svg>
              </button>
            ))}
          </div>
        )}
      </div>

      {r && (
        <details className="sl-why">
          <summary>How Sift scored this</summary>
          <p>{r.explanation}</p>
        </details>
      )}
    </div>
  )
}

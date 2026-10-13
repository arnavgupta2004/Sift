import { useEffect, useState } from 'react'
import { getIndexStatus } from '../api'
import type { IndexStatus as Status } from '../types'

export function IndexStatus() {
  const [status, setStatus] = useState<Status | null>(null)

  useEffect(() => {
    let timer: number | undefined
    let cancelled = false
    async function poll() {
      let busy = true
      try {
        const s = await getIndexStatus()
        if (cancelled) return
        setStatus(s)
        busy = s.phase !== 'idle' || s.files_pending > 0
      } catch {
        busy = true
      }
      timer = window.setTimeout(poll, busy ? 3000 : 30000)
    }
    poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [])

  if (!status) return null

  const pct = status.files_found ? Math.round((status.files_searchable / status.files_found) * 100) : 0
  const n = (x: number) => x.toLocaleString()
  let text: string
  if (status.phase === 'scanning' || status.phase === 'starting') {
    text = `Scanning your laptop… ${n(status.files_found)} files found so far`
  } else if (status.files_pending > 0) {
    text = `Reading your files… ${n(status.files_searchable)} of ${n(status.files_found)} fully searchable (${pct}%)`
  } else {
    text = `Your whole laptop is searchable · ${n(status.files_found)} files`
  }

  return (
    <div className="index-status" title={`Searching: ${status.roots.join(', ')}`}>
      <span className="index-status-text">{text}</span>
      {status.files_pending > 0 && (
        <span className="index-status-bar" aria-hidden="true">
          <span style={{ width: `${pct}%` }} />
        </span>
      )}
      {status.last_error && <span className="index-status-error">Paused: {status.last_error}</span>}
    </div>
  )
}

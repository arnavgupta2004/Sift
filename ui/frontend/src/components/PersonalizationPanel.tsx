import type { PersonalizationInsights } from '../types'

interface Props {
  insights: PersonalizationInsights | null
  loading: boolean
}

const SHORT_DAYS: Record<string, string> = {
  Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed', Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun',
}

export function PersonalizationPanel({ insights, loading }: Props) {
  if (loading && !insights) return <div className="panel insights-panel"><p className="muted">Learning your habits…</p></div>
  if (!insights) return null

  return (
    <div className="panel insights-panel">
      <div className="insights-head">
        <h3>Made for you</h3>
        <p className="muted">Sift ranks these habits higher in your results.</p>
      </div>

      <div className="insight-block">
        <span className="insight-label">File types you use most</span>
        <div className="chip-row">
          {insights.preferred_file_types.length === 0 && <span className="muted">None yet</span>}
          {insights.preferred_file_types.map((t) => (
            <span className="chip" key={t}>.{t}</span>
          ))}
        </div>
      </div>

      <div className="insight-block">
        <span className="insight-label">Opened most often</span>
        {insights.top_files_by_frequency.length === 0 && <span className="muted">Open a few files and they will show up here.</span>}
        <ul className="insight-files">
          {insights.top_files_by_frequency.map((f) => (
            <li key={f.file_id}>
              <span className="insight-file-name" title={f.filename}>{f.filename}</span>
              <span className="insight-meter" aria-label={`${Math.round(f.frequency * 100)}% as often as your most-opened file`}>
                <span style={{ width: `${Math.max(6, f.frequency * 100)}%` }} />
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="insight-block">
        <span className="insight-label">Your weekly routine</span>
        {insights.recurring_patterns.length === 0 && <span className="muted">No routine spotted yet.</span>}
        <ul className="insight-routine">
          {insights.recurring_patterns.map((p, i) => (
            <li key={i}>
              <span className="routine-when">
                {SHORT_DAYS[p.weekday] ?? p.weekday} {String(p.hour).padStart(2, '0')}:00
              </span>
              <span className="routine-files">
                {p.filenames.map((f) => <span key={f} title={f}>{f}</span>)}
              </span>
              <span className="routine-conf" title="Share of weeks this happened">{Math.round(p.confidence * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>

      {insights.active_context_boost_now && (
        <div className="context-boost-banner">
          It's your usual time for {insights.active_context_files.join(', ')}, so {insights.active_context_files.length === 1 ? 'it ranks' : 'they rank'} higher right now.
        </div>
      )}
    </div>
  )
}

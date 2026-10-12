import { useEffect, useState } from 'react'
import { browseFolder } from '../api'
import type { BrowseResult } from '../types'

interface Props {
  startPath?: string
  onChoose: (path: string) => void
  onCancel: () => void
}

export function FolderBrowser({ startPath, onChoose, onCancel }: Props) {
  const [data, setData] = useState<BrowseResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function open(path?: string) {
    try {
      setData(await browseFolder(path))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot open that folder')
    }
  }

  useEffect(() => {
    open(startPath || undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="folder-browser">
      <div className="folder-browser-bar">
        <button className="example-chip" onClick={() => data && open(data.home)} disabled={!data}>
          Home
        </button>
        <button
          className="example-chip"
          onClick={() => data?.parent && open(data.parent)}
          disabled={!data?.parent}
        >
          Up
        </button>
        <span className="folder-browser-path" title={data?.path}>
          <bdi>{data?.path ?? 'Loading…'}</bdi>
        </span>
      </div>

      {error && <div className="error-banner index-folder-error">{error}</div>}

      <ul className="folder-browser-list">
        {data?.entries.length === 0 && <li className="muted folder-browser-empty">No subfolders here</li>}
        {data?.entries.map((e) => (
          <li key={e.path}>
            <button className="folder-browser-item" onClick={() => open(e.path)}>
              {e.name}
            </button>
          </li>
        ))}
      </ul>

      <div className="folder-browser-actions">
        <button className="run-button" onClick={() => data && onChoose(data.path)} disabled={!data}>
          Use this folder
        </button>
        <button className="example-chip" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

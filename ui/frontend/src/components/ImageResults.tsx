import { useState } from 'react'
import { openFile } from '../api'
import type { ImageHit } from '../types'

interface Props {
  hits: ImageHit[]
  userId: number
  searched: boolean
}

export function ImageResults({ hits, userId, searched }: Props) {
  const [openError, setOpenError] = useState<string | null>(null)

  if (hits.length === 0) {
    return (
      <p className="empty-state">
        {searched
          ? 'No images matched. Photos are described by what is in them, so try other words.'
          : 'Describe the picture you remember, like “a dog on a couch” or “a whiteboard with equations”.'}
      </p>
    )
  }

  async function handleOpen(fileId: number) {
    try {
      setOpenError(null)
      await openFile(fileId, userId)
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Could not open the image')
    }
  }

  return (
    <>
      {openError && <div className="error-banner">{openError}</div>}
      <ul className="image-grid">
        {hits.map((h) => (
          <li key={h.file_id}>
            <button className="image-tile" onClick={() => handleOpen(h.file_id)} title={h.path}>
              <img src={`/api/thumbnail/${h.file_id}`} alt={h.filename} loading="lazy" />
              <span>{h.filename}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

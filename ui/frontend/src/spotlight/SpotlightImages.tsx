import type { ImageHit } from '../types'

interface Props {
  hits: ImageHit[]
  selected: number
  onSelect: (index: number) => void
  onOpen: (hit: ImageHit) => void
}

export function SpotlightImages({ hits, selected, onSelect, onOpen }: Props) {
  return (
    <ul className="image-grid" role="listbox" aria-label="Images">
      {hits.map((h, i) => (
        <li key={h.file_id} role="presentation">
          <button
            role="option"
            aria-selected={i === selected}
            className={i === selected ? 'image-tile selected' : 'image-tile'}
            onClick={() => onSelect(i)}
            onDoubleClick={() => onOpen(h)}
            title={h.path}
          >
            <img src={`/api/thumbnail/${h.file_id}`} alt={h.filename} loading="lazy" />
            <span>{h.filename}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

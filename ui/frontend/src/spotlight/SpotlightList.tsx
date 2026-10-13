import { useEffect, useRef } from 'react'
import type { ResultItem } from '../types'
import { folderOf, matchLevel, tidyPath } from '../format'
import { FileIcon } from '../components/FileIcon'

/** One line in the Spotlight list: a search result, or a suggestion when the box is empty. */
export interface Row {
  file_id: number
  filename: string
  path: string
  file_type: string
  section: string
  result?: ResultItem
  note?: string
}

interface Props {
  rows: Row[]
  selected: number
  onSelect: (index: number) => void
  onOpen: (row: Row) => void
}

export function SpotlightList({ rows, selected, onSelect, onOpen }: Props) {
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${selected}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  return (
    <ul className="sl-list" ref={listRef} role="listbox" aria-label="Files">
      {rows.map((row, i) => {
        const header = i === 0 || rows[i - 1].section !== row.section
        const conf = row.result?.confidence
        return (
          <li key={`${row.section}-${row.file_id}`} role="presentation">
            {header && <div className="sl-section">{row.section}</div>}
            <div
              role="option"
              aria-selected={i === selected}
              data-index={i}
              className={i === selected ? 'sl-row selected' : 'sl-row'}
              onMouseMove={() => i !== selected && onSelect(i)}
              onClick={() => onSelect(i)}
              onDoubleClick={() => onOpen(row)}
            >
              <FileIcon fileType={row.file_type} size={i === 0 && row.section === 'Top Hit' ? 34 : 26} />
              <div className="sl-row-text">
                <span className="sl-row-name">{row.filename}</span>
                <span className="sl-row-sub">{row.note ?? tidyPath(folderOf(row.path))}</span>
              </div>
              {conf !== undefined && (
                <span className={`sl-conf conf-${matchLevel(conf)}`} title="How strongly this stands out from the other candidates">
                  {Math.round(conf * 100)}%
                </span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

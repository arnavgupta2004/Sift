// Document-shaped icon tinted by kind, like Finder/Spotlight file icons.
const KINDS: [string, string[]][] = [
  ['pdf', ['pdf']],
  ['doc', ['doc', 'docx', 'rtf', 'odt', 'pages', 'txt', 'md', 'mdx', 'rst', 'tex']],
  ['sheet', ['xls', 'xlsx', 'csv', 'tsv', 'ods', 'numbers']],
  ['slides', ['ppt', 'pptx', 'key', 'odp']],
  ['image', ['png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'bmp', 'tiff', 'svg']],
  ['code', ['py', 'js', 'ts', 'tsx', 'jsx', 'json', 'html', 'css', 'java', 'c', 'h', 'cpp', 'go', 'rs', 'rb', 'sh', 'sql', 'ipynb', 'yaml', 'yml', 'toml', 'xml']],
]

function kindOf(fileType: string): string {
  const t = fileType.toLowerCase()
  return KINDS.find(([, exts]) => exts.includes(t))?.[0] ?? 'other'
}

export function FileIcon({ fileType, size = 32 }: { fileType: string; size?: number }) {
  const label = fileType.slice(0, 4).toUpperCase()
  return (
    <span className={`file-icon kind-${kindOf(fileType)}`} style={{ width: size, height: size * 1.2 }} aria-hidden="true">
      <svg viewBox="0 0 40 48">
        <path className="file-icon-sheet" d="M4 3a3 3 0 0 1 3-3h19l11 11v34a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3Z" />
        <path className="file-icon-fold" d="M26 0v8a3 3 0 0 0 3 3h8Z" />
        <rect className="file-icon-band" x="4" y="28" width="33" height="13" />
        <text x="20.5" y="38" textAnchor="middle">{label}</text>
      </svg>
    </span>
  )
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

/** "yesterday", "3 weeks ago" — how Spotlight-style previews talk about dates. */
export function timeAgo(iso: string | null): string | null {
  if (!iso) return null
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

export function folderOf(path: string): string {
  const cut = path.lastIndexOf('/')
  return cut > 0 ? path.slice(0, cut) : path
}

/** Shortens /home/<user>/... (or /Users/<user>/...) to ~/... */
export function tidyPath(path: string): string {
  return path.replace(/^\/(home|Users)\/[^/]+/, '~')
}

export type MatchLevel = 'strong' | 'good' | 'possible' | 'weak'

export function matchLevel(confidence: number): MatchLevel {
  if (confidence >= 0.85) return 'strong'
  if (confidence >= 0.6) return 'good'
  if (confidence >= 0.35) return 'possible'
  return 'weak'
}

export const MATCH_LABELS: Record<MatchLevel, string> = {
  strong: 'Strong match',
  good: 'Good match',
  possible: 'Possible match',
  weak: 'Weak match',
}

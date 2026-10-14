// Sift's mark: a monochrome pixel magnifying glass, light on a dark tile.
// Drawn on a 32x32 grid from geometry (a ring, a tapered handle with a rounded end and a
// glint on the lens) rather than by hand, so the curves stay even. public/favicon.svg is
// generated from the same shape (see scripts/make_favicon.py).
const GRID = 32
const CENTER = 13 // lens centre, in pixels
const RING_OUTER = 10.4
const RING_INNER = 7.4

type Pixel = { x: number; y: number; alpha: number }

function shade(px: number, py: number): number {
  const dx = px - CENTER
  const dy = py - CENTER
  const d = Math.hypot(dx, dy)
  // along the handle (down-right diagonal) and across it
  const u = (dx + dy) / Math.SQRT2
  const v = (dx - dy) / Math.SQRT2

  if (d >= RING_INNER && d <= RING_OUTER) return 1 // frame
  if (u >= RING_OUTER - 1 && u <= 14.5 && Math.abs(v) <= 2.3) return 1 // neck
  if (u > 14.5 && u <= 20.5 && Math.abs(v) <= 3.1) return 1 // grip
  if (u > 20.5 && Math.hypot(u - 20.5, v) <= 3) return 1 // rounded end
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI
  if (d >= 4.6 && d <= 5.8 && angle >= -165 && angle <= -105) return 0.55 // glint
  if (d < RING_INNER) return 0.07 // the glass itself
  return 0
}

/** Pixels merged into horizontal runs of equal shade, to keep the SVG small. */
function logoRuns(): (Pixel & { width: number })[] {
  const runs: (Pixel & { width: number })[] = []
  for (let y = 0; y < GRID; y++) {
    let run: (Pixel & { width: number }) | null = null
    for (let x = 0; x < GRID; x++) {
      const alpha = shade(x + 0.5, y + 0.5)
      if (run && run.alpha === alpha) {
        run.width++
        continue
      }
      if (run && run.alpha > 0) runs.push(run)
      run = { x, y, alpha, width: 1 }
    }
    if (run && run.alpha > 0) runs.push(run)
  }
  return runs
}

const RUNS = logoRuns()

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox={`0 0 ${GRID} ${GRID}`} shapeRendering="crispEdges" aria-hidden="true">
      {RUNS.map((r) => (
        <rect key={`${r.x}-${r.y}`} x={r.x} y={r.y} width={r.width} height="1" fill="var(--logo-ink)" opacity={r.alpha} />
      ))}
    </svg>
  )
}

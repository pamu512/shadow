/** Parse fenced code blocks from agent text. */
export type TerminalSegment =
  | { type: 'text'; value: string }
  | { type: 'code'; lang: string; value: string }

export function parseFencedCode(text: string): TerminalSegment[] {
  const segments: TerminalSegment[] = []
  const re = /```([\w+-]*)\s*\n([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) segments.push({ type: 'text', value: text.slice(last, m.index) })
    let lang = (m[1] || 'text').toLowerCase().trim()
    if (lang === 'py' || lang === 'python3') lang = 'python'
    if (lang === 'r' || lang === 'rlang') lang = 'r'
    segments.push({ type: 'code', lang, value: m[2].replace(/\n$/, '') })
    last = m.index + m[0].length
  }
  if (last < text.length) segments.push({ type: 'text', value: text.slice(last) })
  if (segments.length === 0) segments.push({ type: 'text', value: text })
  return segments
}

export function hasFencedCode(text: string): boolean {
  return /```[\w+-]*\s*\n/.test(text)
}

export type ForensicTag = 'SYSTEM' | 'EXECUTION' | 'WARNING' | 'OPERATOR' | 'RFI'

export function forensicTagForMessage(role: string, content: string): ForensicTag {
  const u = content.toUpperCase()
  if (role === 'user') return 'OPERATOR'
  if (role === 'system') return 'SYSTEM'
  if (content.trimStart().startsWith('[RFI]')) return 'RFI'
  if (u.trimStart().startsWith('[EXECUTION]')) return 'EXECUTION'
  if (
    u.startsWith('ERR') ||
    u.includes('FAILED') ||
    u.includes('FAULT') ||
    u.includes('ERROR:') ||
    u.includes('WARNING')
  ) {
    return 'WARNING'
  }
  if (
    u.includes('INGEST') ||
    u.includes('SANDBOX') ||
    u.includes('[TOOL') ||
    u.includes('EXIT=') ||
    u.includes('STDOUT:')
  ) {
    return 'EXECUTION'
  }
  return 'SYSTEM'
}

const TAG_COLOR: Record<ForensicTag, string> = {
  SYSTEM: 'text-cyan-400',
  EXECUTION: 'text-fuchsia-400',
  WARNING: 'text-amber-400',
  OPERATOR: 'text-zinc-400',
  RFI: 'text-amber-300',
}

export function tagColorClass(tag: ForensicTag): string {
  return TAG_COLOR[tag]
}

export function formatTerminalTime(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** Short label for the transcript column (replaces raw [SYSTEM] / [OPERATOR] tags). */
export function humanSpeakerLabel(role: string, tag: ForensicTag): string {
  if (role === 'user') return 'You'
  if (role === 'system') return 'System'
  switch (tag) {
    case 'RFI':
      return 'Needs your input'
    case 'WARNING':
      return 'Notice'
    case 'EXECUTION':
      return 'Tool / sandbox'
    case 'OPERATOR':
      return 'You'
    case 'SYSTEM':
    default:
      return 'Assistant'
  }
}

export function speakerAccentClass(role: string, tag: ForensicTag): string {
  if (role === 'user' || tag === 'OPERATOR') return 'text-violet-300/95'
  if (tag === 'WARNING') return 'text-amber-300/95'
  if (tag === 'RFI') return 'text-amber-200/95'
  if (tag === 'EXECUTION') return 'text-fuchsia-300/90'
  return 'text-zinc-200'
}

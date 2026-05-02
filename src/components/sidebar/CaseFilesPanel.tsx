import { lazy, Suspense, useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Trash2 } from 'lucide-react'
import {
  activateCase,
  createCase,
  deleteCase,
  fetchCases,
  fetchCasesActivityBulk,
  patchCase,
  purgeAllCases,
  uploadCaseWithProgress,
} from '../../lib/api'
import { coerceCaseStatus, sortCasesByStatus } from '../../lib/caseSort'
import { clearAllSessionColumnMappings, clearSessionColumnMapping } from '../../lib/sessionColumnMap'
import type { CaseActivitySeries, CaseOut, CaseStatus } from '../../lib/types'
import { GhostButton } from '../ui/ForensicChrome'
import { ForensicModal } from '../ui/ForensicModal'
import { CaseStatusBadge } from './CaseStatusBadge'

const CaseActivitySparkline = lazy(async () => {
  const m = await import('./CaseActivitySparkline')
  return { default: m.CaseActivitySparkline }
})

type Props = {
  activeId: string | null
  onActiveChange: Dispatch<SetStateAction<CaseOut | null>>
}

const STATUS_OPTIONS: CaseStatus[] = ['INVESTIGATING', 'FLAGGED', 'CLEARED']

function formatTs(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatMemoryRel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = Date.now() - t
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h}h ago`
  return formatTs(iso)
}

export function CaseFilesPanel({ activeId, onActiveChange }: Props) {
  const [cases, setCases] = useState<CaseOut[]>([])
  const [name, setName] = useState('New case')
  const [datasetPath, setDatasetPath] = useState('')
  const [newStatus, setNewStatus] = useState<CaseStatus>('INVESTIGATING')
  const [activityById, setActivityById] = useState<Record<string, CaseActivitySeries>>({})
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [purgeOpen, setPurgeOpen] = useState(false)
  const [purgeBusy, setPurgeBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const normalizeList = (list: CaseOut[]): CaseOut[] =>
    sortCasesByStatus(list.map((c) => ({ ...c, status: coerceCaseStatus((c as CaseOut).status) })))

  const reload = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const list = await fetchCases()
      const sorted = normalizeList(list)
      setCases(sorted)
      const active = sorted.find((c) => c.is_active) ?? null
      onActiveChange(active ?? null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [onActiveChange])

  const caseIdsSig = cases.map((c) => c.id).join('|')

  useEffect(() => {
    if (!caseIdsSig) {
      queueMicrotask(() => setActivityById({}))
      return
    }
    const ids = caseIdsSig.split('|').filter(Boolean)
    let cancelled = false
    void fetchCasesActivityBulk(ids).then((m) => {
      if (!cancelled) setActivityById(m)
    })
    return () => {
      cancelled = true
    }
  }, [caseIdsSig])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load cases on mount
    void reload()
  }, [reload])

  const onCreate = async () => {
    setErr(null)
    setUploadPct(null)
    try {
      if (csvFile) {
        setUploadPct(1)
        await uploadCaseWithProgress(name, csvFile, newStatus, setUploadPct)
        setCsvFile(null)
        if (fileRef.current) fileRef.current.value = ''
      } else if (datasetPath.trim()) {
        await createCase(name, datasetPath.trim(), newStatus)
      } else {
        setErr('Attach a CSV file (recommended) or enter an absolute dataset path.')
        return
      }
      setName('New case')
      setNewStatus('INVESTIGATING')
      setDatasetPath('')
      await reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      window.setTimeout(() => setUploadPct(null), 500)
    }
  }

  const onActivate = async (id: string) => {
    try {
      const c = await activateCase(id)
      onActiveChange({ ...c, status: coerceCaseStatus(c.status) })
      await reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  const onStatusChange = async (caseId: string, status: CaseStatus) => {
    try {
      const updated = await patchCase(caseId, { status })
      setCases((prev) => normalizeList(prev.map((x) => (x.id === caseId ? { ...updated, status: coerceCaseStatus(updated.status) } : x))))
      onActiveChange((cur) => (cur?.id === caseId ? { ...cur, status } : cur))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  const onRemoveOne = async (c: CaseOut) => {
    if (!window.confirm(`Remove case "${c.name}" and its ingested CSV / DuckDB files? This cannot be undone.`)) return
    setErr(null)
    try {
      await deleteCase(c.id)
      clearSessionColumnMapping(c.id)
      await reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  const onPurgeAll = async () => {
    setPurgeBusy(true)
    setErr(null)
    try {
      await purgeAllCases()
      clearAllSessionColumnMappings()
      setPurgeOpen(false)
      await reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setPurgeBusy(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-2.5 bg-[#09090b]/98 p-2.5 backdrop-blur-sm">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Registry</div>
        <div className="mt-0.5 text-sm font-semibold tracking-tight text-zinc-100">Case memory</div>
      </div>
      <GhostButton onClick={() => void reload()} className="w-full justify-center !text-zinc-500 hover:!text-zinc-200">
        {loading ? 'Syncing…' : 'Refresh index'}
      </GhostButton>
      <button
        type="button"
        disabled={loading || cases.length === 0}
        className="w-full rounded-lg border border-red-500/35 bg-red-950/20 px-2 py-1.5 text-[11px] font-medium text-red-200/95 hover:bg-red-950/35 disabled:pointer-events-none disabled:opacity-40"
        onClick={() => setPurgeOpen(true)}
      >
        Remove all cases and CSV data
      </button>
      <ForensicModal open={purgeOpen} onClose={() => !purgeBusy && setPurgeOpen(false)} title="Remove everything?">
        <p className="text-xs leading-relaxed text-zinc-400">
          This deletes <span className="font-medium text-zinc-300">all registered cases</span>, their ingested files under{' '}
          <span className="font-mono text-zinc-500">.data/storage/</span>, matching rows in the{' '}
          <span className="font-mono text-zinc-500">global warehouse</span> DuckDB, and clears browser session column hints. Your
          SQLite file stays; only case rows are removed.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={purgeBusy}
            className="rounded-lg border border-zinc-600 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
            onClick={() => setPurgeOpen(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={purgeBusy}
            className="rounded-lg border border-red-500/50 bg-red-950/50 px-3 py-1.5 text-xs font-semibold text-red-100 hover:bg-red-900/45 disabled:opacity-40"
            onClick={() => void onPurgeAll()}
          >
            {purgeBusy ? 'Removing…' : 'Remove all'}
          </button>
        </div>
      </ForensicModal>
      <ForensicModal open={!!err} onClose={() => setErr(null)} title="Channel fault">
        <pre className="whitespace-pre-wrap font-mono text-[11px] text-amber-400">{err}</pre>
      </ForensicModal>
      <nav className="min-h-0 flex-1 space-y-2 overflow-auto pr-0.5">
        {cases.length === 0 && !loading && (
          <p className="font-mono text-[11px] text-zinc-600">No cases indexed.</p>
        )}
        {cases.map((c) => {
          const active = c.id === activeId
          const flagged = c.status === 'FLAGGED'
          const rowCount =
            c.schema_summary && typeof c.schema_summary === 'object' && !Array.isArray(c.schema_summary)
              ? (c.schema_summary as { row_count?: unknown }).row_count
              : null
          const rowsLabel = typeof rowCount === 'number' && Number.isFinite(rowCount) ? `${rowCount} rows` : null
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => void onActivate(c.id)}
              className={`relative flex w-full flex-col gap-2 rounded-lg border p-2.5 text-left transition-colors ${
                active ? 'pl-3' : ''
              } ${
                active
                  ? 'border-fuchsia-500/40 bg-zinc-900/85 shadow-[0_0_0_1px_rgba(192,38,211,0.15)]'
                  : flagged
                    ? 'border-red-500/50 bg-red-950/15 shadow-[0_0_16px_rgba(239,68,68,0.12)] ring-1 ring-red-500/25'
                    : 'border-zinc-800 bg-zinc-950/50 hover:border-zinc-700 hover:bg-zinc-900/40'
              }`}
            >
              {active && (
                <span
                  className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-fuchsia-500 shadow-[0_0_8px_rgba(192,38,211,0.6)]"
                  aria-hidden
                />
              )}
              <div className="flex items-start justify-between gap-2 pl-0.5">
                <span className="min-w-0 truncate pt-0.5 text-xs font-medium text-zinc-200">{c.name}</span>
                <div className="flex shrink-0 items-start gap-1">
                  <button
                    type="button"
                    title="Remove case and files"
                    className="rounded p-0.5 text-zinc-600 hover:bg-zinc-800 hover:text-red-400"
                    onClick={(e) => {
                      e.stopPropagation()
                      void onRemoveOne(c)
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    <span className="sr-only">Remove case</span>
                  </button>
                  <CaseStatusBadge status={c.status} />
                </div>
              </div>
              <div className="relative pl-0.5">
                <Suspense fallback={<div className="h-7 max-w-[10.5rem] rounded bg-zinc-900/40" aria-hidden />}>
                  <CaseActivitySparkline series={activityById[c.id]} />
                </Suspense>
                <div className="pointer-events-none absolute bottom-0.5 left-1 flex flex-wrap gap-1">
                  <span className="rounded border border-zinc-800/90 bg-zinc-950/90 px-1 py-px font-mono text-[8px] font-medium text-amber-200/95 shadow-sm">
                    {c.lead_count ?? 0} leads
                  </span>
                  {rowsLabel ? (
                    <span className="rounded border border-zinc-800/90 bg-zinc-950/90 px-1 py-px font-mono text-[8px] font-medium text-emerald-200/90 shadow-sm">
                      {rowsLabel}
                    </span>
                  ) : null}
                </div>
              </div>
              <div
                className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-0.5 font-mono text-[9px] text-zinc-600"
                title="Script runs and audit timestamps (lead / row density on sparkline)"
              >
                <span>{c.script_run_count ?? 0} runs</span>
                <span className="text-zinc-800" aria-hidden>
                  ·
                </span>
                <span>{formatMemoryRel(c.last_memory_at)}</span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 pl-0.5">
                <span className="font-mono text-[10px] text-zinc-600">{formatTs(c.created_at)}</span>
                <select
                  value={c.status}
                  onClick={(e) => e.stopPropagation()}
                  onMouseDown={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    e.stopPropagation()
                    void onStatusChange(c.id, e.target.value as CaseStatus)
                  }}
                  className="max-w-[9rem] cursor-pointer rounded-md border border-zinc-700/80 bg-zinc-900/90 py-0.5 pl-1.5 pr-6 font-mono text-[10px] text-zinc-400 focus:border-violet-500/40 focus:outline-none"
                  aria-label={`Status for ${c.name}`}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s === 'INVESTIGATING' ? 'Investigating' : s === 'FLAGGED' ? 'Flagged' : 'Cleared'}
                    </option>
                  ))}
                </select>
              </div>
            </button>
          )
        })}
      </nav>
      <div className="mt-auto space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/70 p-2.5 backdrop-blur-sm">
        <input
          className="w-full rounded-lg border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-700 focus:outline-none"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New case label"
        />
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="shrink-0 rounded-lg border border-zinc-700 bg-zinc-900/80 px-2.5 py-1.5 text-[11px] text-zinc-300 hover:border-zinc-600"
          >
            CSV…
          </button>
          <span className="min-w-0 flex-1 truncate pt-1.5 font-mono text-[10px] text-zinc-500" title={csvFile?.name}>
            {csvFile ? csvFile.name : 'No file — upload to run DuckDB ingestion'}
          </span>
        </div>
        <input
          className="w-full rounded-lg border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-700 focus:outline-none"
          value={datasetPath}
          onChange={(e) => setDatasetPath(e.target.value)}
          placeholder="/absolute/path/data.csv (optional)"
        />
        <select
          value={newStatus}
          onChange={(e) => setNewStatus(e.target.value as CaseStatus)}
          className="w-full cursor-pointer rounded-lg border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-xs text-zinc-300 focus:border-zinc-700 focus:outline-none"
          aria-label="Initial case status"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === 'INVESTIGATING' ? 'Investigating' : s === 'FLAGGED' ? 'Flagged' : 'Cleared'}
            </option>
          ))}
        </select>
        {uploadPct !== null ? (
          <div
            className="h-1.5 w-full overflow-hidden rounded bg-zinc-800"
            role="progressbar"
            aria-valuenow={uploadPct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-gradient-to-r from-fuchsia-600/90 to-violet-500/90 transition-[width] duration-150"
              style={{ width: `${Math.min(100, uploadPct)}%` }}
            />
          </div>
        ) : null}
        <button
          type="button"
          disabled={uploadPct !== null}
          className="w-full rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/10 px-2 py-2 text-xs font-medium text-fuchsia-200 shadow-[0_0_14px_rgba(168,85,247,0.18)] transition-colors hover:border-fuchsia-400/55 hover:bg-fuchsia-500/15 disabled:pointer-events-none disabled:opacity-50"
          onClick={() => void onCreate()}
        >
          Register case
        </button>
      </div>
    </div>
  )
}

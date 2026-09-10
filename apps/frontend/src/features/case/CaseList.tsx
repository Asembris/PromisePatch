/**
 * The cases a worker can open, newest first.
 *
 * It exists for one reason beyond navigation: a browser that has lost its address — a new tab,
 * a cleared URL, a bookmark to the root — still has to be able to get back to the case it was
 * reading. The list is that path, and every row it shows is a durable case rather than
 * something this session remembers having opened.
 *
 * Each row shows the state and the worker's own opening sentence. It deliberately shows no
 * outcome and no count: a summary that said "3 recovered" would be a claim composed on a
 * screen, and the place claims like that are allowed to be made is the workspace, from the
 * backend's own words.
 */
import type { ReactNode } from 'react'
import { useCases } from '../../api/queries'
import type { CaseSummaryView } from '../../api/types'
import { Badge, Notice, Panel } from '../../components/primitives'
import { formatDateTime } from '../../components/time'

export function CaseList({ onOpen }: { onOpen: (caseId: string) => void }): ReactNode {
  const cases = useCases(true)

  return (
    <Panel
      title="Cases"
      subtitle={cases.data ? `${cases.data.cases.length} on record` : undefined}
    >
      {cases.isPending ? (
        <Notice>Loading cases…</Notice>
      ) : cases.isError ? (
        <Notice tone="bad">Cases could not be loaded. They will be retried on the next event.</Notice>
      ) : cases.data.cases.length === 0 ? (
        <Notice>
          No case has been opened. Report a physical exception through the conversational surface
          to open one.
        </Notice>
      ) : (
        <ul className="divide-y divide-edge" data-testid="case-list">
          {cases.data.cases.map((row) => (
            <CaseRow key={row.case_id} row={row} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

function CaseRow({
  row,
  onOpen,
}: {
  row: CaseSummaryView
  onOpen: (caseId: string) => void
}): ReactNode {
  return (
    <li data-testid="case-row" data-case-id={row.case_id}>
      <button
        type="button"
        onClick={() => {
          onOpen(row.case_id)
        }}
        className="w-full px-4 py-3 text-left hover:bg-surface"
      >
        <div className="flex flex-wrap items-baseline gap-2">
          <Badge tone={row.needs_owner_attention ? 'bad' : 'neutral'}>{row.headline}</Badge>
          <span className="text-sm">
            {row.reported_text === null ? row.sentence : `“${row.reported_text}”`}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted">
          opened {formatDateTime(row.opened_at) ?? row.opened_at}
          {row.needs_owner_attention ? ' · needs the owner' : ''}
        </p>
      </button>
    </li>
  )
}

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
import { CaseHeadlineBadge } from '../../components/badges'
import { Message, Panel } from '../../components/surfaces'
import { formatDateTime } from '../../components/time'

export function CaseList({ onOpen }: { onOpen: (caseId: string) => void }): ReactNode {
  const cases = useCases(true)

  return (
    <Panel
      title="Cases"
      subtitle={cases.data ? `${cases.data.cases.length} on record` : undefined}
    >
      {cases.isPending ? (
        <Message>Loading cases…</Message>
      ) : cases.isError ? (
        <Message tone="bad">Cases could not be loaded. They will be retried on the next event.</Message>
      ) : cases.data.cases.length === 0 ? (
        <Message>
          No case has been opened. A case starts when somebody says what went wrong.
        </Message>
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
          <CaseHeadlineBadge headline={row.headline} />
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

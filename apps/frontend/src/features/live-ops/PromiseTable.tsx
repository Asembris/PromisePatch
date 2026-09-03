/**
 * The order book.
 *
 * Every row comes from `/api/promises` and the list is rendered in the order the backend
 * returned it. There is no client-side sort, and there are no hard-coded promise labels: the
 * backend does not expose an "A"–"F" designation, so inventing one from a fixture id would be
 * putting a caption on the screen that no API says is true. Rows are identified by the
 * external order id, which is what an operator would quote.
 *
 * `classification` and the case pointers are `null` for a promise no case has touched. That is
 * rendered as "no open case" — not as `UNAFFECTED`, which is a decision the engine makes about
 * a specific exception and which nothing here is entitled to assert.
 */
import type { ReactNode } from 'react'
import type { OrderLineView, PromiseView } from '../../api/types'
import { Badge, StateBadge, Value } from '../../components/primitives'
import { formatDateTime, formatTime } from '../../components/time'

const CELL = 'px-3 py-2 align-top'

export function PromiseTable({ promises }: { promises: readonly PromiseView[] }): ReactNode {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[64rem] border-collapse text-sm">
        <caption className="sr-only">
          Customer promises, in the order the API returned them: by due time, then external
          order id.
        </caption>
        <thead>
          <tr className="border-b border-edge bg-surface text-left text-xs font-medium text-muted">
            <th scope="col" className={CELL}>
              Due
            </th>
            <th scope="col" className={CELL}>
              Customer
            </th>
            <th scope="col" className={CELL}>
              Order
            </th>
            <th scope="col" className={CELL}>
              Items
            </th>
            <th scope="col" className={CELL}>
              Production
            </th>
            <th scope="col" className={CELL}>
              Constraints
            </th>
            <th scope="col" className={CELL}>
              Case
            </th>
          </tr>
        </thead>
        <tbody>
          {promises.map((promise) => (
            <PromiseRow key={promise.id} promise={promise} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PromiseRow({ promise }: { promise: PromiseView }): ReactNode {
  return (
    <tr data-testid="promise-row" data-promise-id={promise.id} className="border-b border-edge last:border-0">
      {/* Date first, then time. The order book routinely spans several days, and leading with
          the clock made a correctly ordered list read as though it jumped backwards — 19:30
          followed by 11:00 is ascending only once the day is the thing the eye reads first. */}
      <td className={`${CELL} whitespace-nowrap`}>
        <div className="font-medium">{formatDateTime(promise.due_at)}</div>
        <div className="text-xs text-muted">order due {formatTime(promise.order_due_at)}</div>
      </td>

      <td className={CELL}>
        <div className="font-medium">{promise.customer.name}</div>
        <div className="font-mono text-xs text-muted">{promise.customer.id}</div>
      </td>

      <td className={CELL}>
        <div className="font-mono text-xs">{promise.external_id}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <StateBadge state={promise.order_state} />
          <Badge>v{promise.external_version}</Badge>
        </div>
      </td>

      <td className={CELL}>
        <ul className="space-y-2">
          {promise.lines.map((line) => (
            <li key={line.id}>
              <LineSummary line={line} />
            </li>
          ))}
        </ul>
      </td>

      <td className={CELL}>
        <ul className="space-y-2">
          {promise.lines.map((line) => (
            <li key={line.id}>
              <TaskSummary line={line} />
            </li>
          ))}
        </ul>
      </td>

      <td className={CELL}>
        {promise.constraints.length === 0 ? (
          <span className="text-xs text-muted">none recorded</span>
        ) : (
          <ul className="space-y-1">
            {promise.constraints.map((constraint) => (
              <li key={constraint.id} className="text-xs">
                <Badge tone="warn">{constraint.kind}</Badge>{' '}
                <span className="font-mono">
                  <Value>{constraint.resource_id}</Value>
                </span>
                <div className="text-muted">
                  recorded by {constraint.recorded_by} · {formatDateTime(constraint.recorded_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </td>

      <td className={CELL}>
        {promise.classification === null && promise.track_state === null ? (
          <span className="text-xs text-muted">no open case</span>
        ) : (
          <div className="space-y-1">
            <StateBadge state={promise.classification} />
            <div>
              <StateBadge state={promise.track_state} />
            </div>
            {promise.case_id === null ? null : (
              <div className="font-mono text-[11px] text-muted">{promise.case_id}</div>
            )}
          </div>
        )}
      </td>
    </tr>
  )
}

/** What is being made, and which authored version it is pinned to. */
function LineSummary({ line }: { line: OrderLineView }): ReactNode {
  return (
    <div>
      <div>
        <span className="font-medium">{line.recipe_version.recipe_name}</span>{' '}
        <span className="text-muted">× {line.quantity}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1">
        {/* The pinned version is the point: a recovery re-points a line at another authored
            version and never derives one, so the version number and its author are shown. */}
        <Badge tone="info">v{line.recipe_version.version_no}</Badge>
        <span className="text-[11px] text-muted">by {line.recipe_version.authored_by}</span>
      </div>
      {line.customization_note === '' ? null : (
        <div className="mt-0.5 text-xs text-muted">{line.customization_note}</div>
      )}
      {line.reservations.length === 0 ? null : (
        <div className="mt-1 text-[11px] text-muted">
          reserves{' '}
          {line.reservations.map((reservation, index) => (
            <span key={reservation.id}>
              {index > 0 ? ', ' : ''}
              <span className="font-mono">
                <Value>{reservation.quantity}</Value>
              </span>{' '}
              {reservation.resource_name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** Task state, timing and the equipment it is scheduled on. */
function TaskSummary({ line }: { line: OrderLineView }): ReactNode {
  const task = line.task
  if (task === null) return <span className="text-xs text-muted">no task</span>
  return (
    <div>
      <StateBadge state={task.state} />
      <div className="mt-0.5 text-[11px] text-muted">
        <Value>{formatTime(task.scheduled_start)}</Value> → <Value>{formatTime(task.scheduled_end)}</Value>
      </div>
      <div className="text-[11px]">
        <Value>{task.equipment_name}</Value>
      </div>
      {task.held_by_case_id === null ? null : <Badge tone="warn">held by case</Badge>}
    </div>
  )
}

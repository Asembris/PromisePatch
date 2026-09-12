/**
 * The one screen.
 *
 * It composes three reads and owns none of them. The order book is rendered in the backend's
 * order, the resource figures are the engine's, and the only thing the feed does is decide
 * when to ask for both again.
 *
 * `as_of` is shown because it is the honest answer to "how current is this": it is the highest
 * domain event sequence the read transaction could see, and it is the coordinate the feed's
 * own cursor is expressed in — so an operator can compare the two directly.
 */
import type { ReactNode } from 'react'
import { usePromises, useResources } from '../../api/queries'
import type { StreamState } from '../../api/useEventStream'
import { Message, Panel } from '../../components/surfaces'
import { formatDateTime } from '../../components/time'
import { CaseList } from '../case/CaseList'
import { PromiseTable } from './PromiseTable'
import { EquipmentList, IngredientTable } from './ResourcePanel'

export function LiveOperations({
  stream,
  onOpenCase,
}: {
  stream: StreamState
  onOpenCase: (caseId: string) => void
}): ReactNode {
  const promises = usePromises(true)
  const resources = useResources(true)

  return (
    <main className="mx-auto max-w-[100rem] space-y-5 px-4 py-5 sm:px-6 sm:py-6">
      <SummaryBar
        promiseCount={promises.data?.promises.length ?? null}
        ingredientCount={resources.data?.ingredients.length ?? null}
        equipmentCount={resources.data?.equipment.length ?? null}
        asOf={promises.data?.as_of ?? null}
        generatedAt={promises.data?.generated_at ?? null}
        stream={stream}
      />

      <CaseList onOpen={onOpenCase} />

      <Panel
        title="Customer promises"
        subtitle={
          promises.data
            ? `${promises.data.promises.length} in the order book · as of sequence ${promises.data.as_of}`
            : undefined
        }
      >
        {promises.isPending ? (
          <Message>Loading the order book…</Message>
        ) : promises.isError ? (
          <Message tone="bad">The order book could not be loaded. It will retry on the next event.</Message>
        ) : promises.data.promises.length === 0 ? (
          <Message>The order book is empty. No accepted promise is on record.</Message>
        ) : (
          <PromiseTable promises={promises.data.promises} />
        )}
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[3fr_2fr]">
        <Panel
          title="Ingredients"
          subtitle={
            resources.data
              ? `available by ${formatDateTime(resources.data.at) ?? resources.data.at}`
              : undefined
          }
        >
          {resources.isPending ? (
            <Message>Loading resource availability…</Message>
          ) : resources.isError ? (
            <Message tone="bad">Resource availability could not be loaded.</Message>
          ) : resources.data.ingredients.length === 0 ? (
            <Message>No ingredients are loaded.</Message>
          ) : (
            <IngredientTable ingredients={resources.data.ingredients} at={resources.data.at} />
          )}
        </Panel>

        <Panel title="Equipment">
          {resources.isPending ? (
            <Message>Loading equipment…</Message>
          ) : resources.isError ? (
            <Message tone="bad">Equipment state could not be loaded.</Message>
          ) : resources.data.equipment.length === 0 ? (
            <Message>No equipment is loaded.</Message>
          ) : (
            <EquipmentList equipment={resources.data.equipment} />
          )}
        </Panel>
      </div>
    </main>
  )
}

function SummaryBar({
  promiseCount,
  ingredientCount,
  equipmentCount,
  asOf,
  generatedAt,
  stream,
}: {
  promiseCount: number | null
  ingredientCount: number | null
  equipmentCount: number | null
  asOf: number | null
  generatedAt: string | null
  stream: StreamState
}): ReactNode {
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <Stat label="Promises" value={promiseCount} />
      <Stat label="Ingredients" value={ingredientCount} />
      <Stat label="Equipment" value={equipmentCount} />
      <Stat label="Read as of seq" value={asOf} />
      <div className="rounded-lg border border-edge bg-panel px-3 py-2">
        <dt className="text-[11px] font-medium tracking-wide text-muted uppercase">Feed</dt>
        <dd className="mt-0.5 text-sm">
          {stream.eventsReceived} event{stream.eventsReceived === 1 ? '' : 's'} this connection
          <div className="text-[11px] text-muted">
            read generated {generatedAt === null ? '—' : formatDateTime(generatedAt)}
          </div>
        </dd>
      </div>
    </dl>
  )
}

function Stat({ label, value }: { label: string; value: number | null }): ReactNode {
  return (
    <div className="rounded-lg border border-edge bg-panel px-3 py-2">
      <dt className="text-[11px] font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 font-mono text-lg tabular-nums">{value === null ? '—' : value}</dd>
    </div>
  )
}

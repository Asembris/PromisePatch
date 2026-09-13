/**
 * The landing surface: the cases, and — one click below them — the bakery they are about.
 *
 * This screen used to open on five figures in tiles and a full-width order book, with the cases
 * somewhere underneath. That arrangement made two claims the product does not make. It read as
 * a dashboard, which P7.1 forbids by name: a tile with a number in it invites a reader to watch
 * the number, and there is no number here worth watching. And it put the order book first, which
 * says the orders are the subject. They are not. **The subject is a case**, and the orders are
 * the context a case is understood against.
 *
 * So the cases land, and the order book is secondary by construction:
 *
 * - **It is behind a disclosure**, closed until somebody asks. Reaching it costs one click and
 *   nothing is hidden from anybody — every order, reservation, constraint, ingredient and piece
 *   of equipment the backend returns is still rendered, in the backend's own order.
 * - **There is no tile, chart, trend or feed.** The only freshness statement is the sequence the
 *   read saw, in a sentence, because that is the honest answer to "how current is this" and not
 *   a metric anybody is being asked to admire.
 * - **There is no count composed on this screen.** The panels used to print the length of the
 *   list they had just rendered, which is a figure reporting on the rendering rather than on the
 *   bakery. The lists are shown; nothing counts them.
 *
 * It composes three reads and owns none of them. The only thing the feed does is decide when to
 * ask for them again.
 */
import type { ReactNode } from 'react'
import { usePromises, useResources } from '../../api/queries'
import type { StreamState } from '../../api/useEventStream'
import { Disclosure } from '../../components/disclosure'
import { Message, Panel } from '../../components/surfaces'
import { formatDateTime } from '../../components/time'
import { CaseList } from '../case/CaseList'
import { ReportEntry } from '../case/ReportEntry'
import { PromiseTable } from './PromiseTable'
import { EquipmentList, IngredientTable } from './ResourcePanel'

export function LiveOperations({
  stream,
  onOpenCase,
}: {
  stream: StreamState
  onOpenCase: (caseId: string) => void
}): ReactNode {
  return (
    <main className="mx-auto max-w-[76rem] space-y-5 px-4 py-5 sm:px-6 sm:py-6">
      {/* Above the list, because a worker arriving with something to say has no row to click.
          It draws itself only for a principal the backend says may attest, so an observer
          never sees it — not greyed out, not at all. */}
      <ReportEntry onOpened={onOpenCase} />
      <CaseList onOpen={onOpenCase} />
      <OrderContext stream={stream} />
    </main>
  )
}

/**
 * The bakery as the backend currently reports it, kept for the reader who asks for it.
 *
 * Demoted, not deleted. These are real reads of real state, and a promise's pinned recipe
 * version, a no-substitution constraint or an open-ended outage is exactly what somebody checks
 * when they want to know whether a case's reasoning was about anything. What changed is where
 * it sits: under the cases, behind a plain label, with nothing about it styled as a headline.
 */
function OrderContext({ stream }: { stream: StreamState }): ReactNode {
  const promises = usePromises(true)
  const resources = useResources(true)

  return (
    <section aria-label="Order book and resources" className="pt-1">
      <Disclosure
        summary="the order book, and what it depends on"
        testId="order-context"
        tone="loud"
      >
        <div className="mt-3 space-y-4">
          <Freshness
            asOf={promises.data?.as_of ?? null}
            generatedAt={promises.data?.generated_at ?? null}
            stream={stream}
          />

          <Panel title="Customer promises">
            {promises.isPending ? (
              <Message>Loading the order book…</Message>
            ) : promises.isError ? (
              <Message tone="bad">
                The order book could not be loaded. It will retry on the next event.
              </Message>
            ) : promises.data.promises.length === 0 ? (
              <Message>The order book is empty. No accepted promise is on record.</Message>
            ) : (
              <PromiseTable promises={promises.data.promises} />
            )}
          </Panel>

          <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
            <Panel
              title="Ingredients"
              subtitle={
                resources.data
                  ? `quantities as they stand by ${formatDateTime(resources.data.at) ?? resources.data.at}`
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
        </div>
      </Disclosure>
    </section>
  )
}

/**
 * How current this is, as a sentence rather than as a figure.
 *
 * `as_of` is the highest domain event sequence the read transaction could see, and it is the
 * coordinate the feed's own cursor is expressed in — so the two can be compared directly. It
 * is worth saying and it is not worth a tile: a number in a box on a landing screen is a metric
 * whether or not anybody meant it as one.
 */
function Freshness({
  asOf,
  generatedAt,
  stream,
}: {
  asOf: number | null
  generatedAt: string | null
  stream: StreamState
}): ReactNode {
  return (
    <p className="text-meta text-muted" data-testid="order-context-freshness">
      {asOf === null ? (
        'This has not been read yet.'
      ) : (
        <>
          Read up to sequence <span className="font-mono tabular-nums">{asOf}</span>
          {generatedAt === null ? null : <> at {formatDateTime(generatedAt)}</>}.
        </>
      )}{' '}
      {stream.eventsReceived} event{stream.eventsReceived === 1 ? '' : 's'} have arrived on this
      connection.
    </p>
  )
}

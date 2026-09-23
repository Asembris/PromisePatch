/**
 * The customer's page: one question about one order, and two words to answer it with.
 *
 * The only screen in PromisePatch drawn for somebody who is not signed in and cannot be. There
 * is no session, no account and nothing to create one with — what got them here is a link, and
 * a link proves possession, never identity. So the page is built the way you build something a
 * stranger might be holding: it shows what the message on their own channel already said, and
 * it stops.
 *
 * **It renders the backend's reading and computes nothing.** Whether the question is still open
 * is `answerable`, decided on the server against the database's own clock. A page that compared
 * `answer_by` to the device's clock would be a second, weaker deadline kept on somebody's
 * phone — and the two disagreeing is exactly the ambiguity the consent protocol exists not to
 * have. This file therefore contains no date comparison at all.
 *
 * **It shows differences that exist.** Each line renders only when the response carries it.
 * There is no placeholder row, no "no change", no dash to decode, and no price — PromisePatch
 * models no amount anywhere, so a money line here would be a number nothing computed.
 *
 * **It asserts nothing about safety.** The change is named, exactly, and that is the whole of
 * it. No reassurance, no "should be fine", no dietary claim: §16.1 gives this product no
 * allergen knowledge and the page must not sound as though it has some.
 *
 * **It never says "approved" before the protocol does.** A stored answer reads `RECEIVED`, and
 * the page says so in those terms. The decision is a row written under the case lock, past the
 * sender check and the deadline check, and this screen reports it only once it exists.
 *
 * On colour: the choice is drawn in the `ask` channel — the authority tone that means *the
 * customer decides* — and never in `brand`. `brand` is the colour a worker presses to confirm a
 * plan, and the visual system keeps customer consent and worker confirmation off one another's
 * colour on purpose. Decline is a neutral outline rather than a danger treatment: saying no is
 * a legitimate answer, not an error.
 *
 * Mobile-first because this is read on a phone, standing up, once. One column, a 16px gutter,
 * and targets big enough to press without aiming.
 */
import type { ReactNode } from 'react'
import { useAnswerCustomerApproval, useCustomerApproval } from '../../api/queries'
import { ApiError } from '../../api/client'
import { PromisePatchLockup } from '../../components/Brand'
import { formatDateTime } from '../../components/time'
import type { CustomerApprovalResponse } from '../../api/types'

/**
 * What each phase says at the top of the page.
 *
 * An exhaustive table over the backend's closed vocabulary rather than a chain of conditionals,
 * for the reason `components/vocabulary.ts` gives: a phase the backend adds should be a missing
 * entry somebody notices, not a blank heading a customer is left staring at.
 *
 * Every sentence is about a row. `RECEIVED` says the answer is kept and does not say what it
 * did; `EXPIRED` and `SUPERSEDED` both say that nothing was done, because on both of those
 * paths nothing was.
 */
const HEADLINE: Record<string, { title: string; sentence: string }> = {
  OPEN: {
    title: 'We need your decision',
    sentence: 'An ingredient for your order did not arrive, so we cannot make it as ordered.',
  },
  RECEIVED: {
    title: 'Thank you — we have your answer',
    sentence: 'It is saved. The bakery is reading it now; this page will update by itself.',
  },
  APPROVED: {
    title: 'You approved this change',
    sentence: 'Your answer is on the record.',
  },
  DECLINED: {
    title: 'You declined this change',
    sentence: 'Your answer is on the record.',
  },
  EXPIRED: {
    title: 'This question has closed',
    sentence: 'No answer was recorded in time, and nothing was done to your order because of it.',
  },
  SUPERSEDED: {
    title: 'This question no longer applies',
    sentence: 'Your order changed after you were asked, and nothing was done because of it.',
  },
  CLOSED: {
    title: 'This link does not open anything',
    sentence: 'If you were expecting a question about an order, please contact the bakery.',
  },
}

/** The fail-closed heading: never a button, never a claim about what happened. */
const UNKNOWN_PHASE = {
  title: 'This question is closed',
  sentence: 'Nothing here is waiting for you.',
}

export function CustomerApproval({ token }: { token: string }): ReactNode {
  const reading = useCustomerApproval(token)
  const answer = useAnswerCustomerApproval(token)

  if (reading.isPending) {
    return (
      <Shell>
        <p className="text-sm text-muted" role="status">
          Opening your order…
        </p>
      </Shell>
    )
  }

  if (reading.isError) {
    // A link that does not verify and a bakery that cannot be reached are different things and
    // are said differently. Neither says which half of a signature was wrong.
    const unknownLink = reading.error instanceof ApiError && reading.error.status === 404
    return (
      <Shell>
        <div role="alert" className="space-y-2">
          <h1 className="text-lg font-semibold text-ink">
            {unknownLink ? 'This link does not open anything' : 'We cannot reach the bakery'}
          </h1>
          <p className="text-sm text-muted">
            {unknownLink
              ? 'If you were expecting a question about an order, please contact the bakery.'
              : 'Nothing about your order has changed; this page simply cannot read it. Try again in a moment.'}
          </p>
        </div>
      </Shell>
    )
  }

  const view = reading.data
  const headline = HEADLINE[view.phase] ?? UNKNOWN_PHASE

  return (
    <Shell>
      <div className="space-y-6" data-testid="customer-approval" data-phase={view.phase}>
        <header className="space-y-2">
          <h1 className="text-lg font-semibold text-ink">{headline.title}</h1>
          <p className="text-sm text-muted">{headline.sentence}</p>
        </header>

        <Order view={view} />
        <Change view={view} />

        {view.answerable ? (
          <Choice
            answerBy={formatDateTime(view.answer_by)}
            onAnswer={(choice) => {
              answer.mutate(choice)
            }}
            pending={answer.isPending}
            failed={answer.isError}
          />
        ) : (
          <Settled view={view} />
        )}

        {view.option_code === null ? null : (
          <p className="text-xs text-muted">
            Change reference <span className="font-mono text-ink">{view.option_code}</span>
          </p>
        )}
      </div>
    </Shell>
  )
}

/** Who this is about and which order, when the link opens one at all. */
function Order({ view }: { view: CustomerApprovalResponse }): ReactNode {
  if (view.order_reference === null) return null
  const due = formatDateTime(view.due_at)
  return (
    <section className="rounded-card border border-edge bg-card p-4">
      <h2 className="text-label font-semibold text-muted uppercase">Your order</h2>
      <p className="mt-2 text-base text-ink">
        {view.customer_name === null ? null : <>{view.customer_name} · </>}
        <span className="font-mono">{view.order_reference}</span>
      </p>
      {due === null ? null : <p className="mt-1 text-sm text-muted">Due {due}</p>}
    </section>
  )
}

/**
 * The exact change, and nothing that is not a change.
 *
 * The whole section is withheld when the response carries neither product: a heading with
 * nothing under it reads as a page that failed to load, and a page that invented a product
 * name to fill the gap would be worse than one that says less.
 */
function Change({ view }: { view: CustomerApprovalResponse }): ReactNode {
  if (view.from_product === null && view.to_product === null) return null
  return (
    <section className="rounded-card border border-edge bg-card p-4" data-testid="proposed-change">
      <h2 className="text-label font-semibold text-muted uppercase">The change we propose</h2>
      <dl className="mt-3 space-y-3 text-sm">
        {view.from_product === null ? null : <Line term="You ordered" value={view.from_product} />}
        {view.to_product === null ? null : (
          <Line term="We would make" value={view.to_product} emphasis />
        )}
        {view.affected_resource === null || view.substitute_resource === null ? null : (
          <Line
            term="Ingredient"
            value={`${view.substitute_resource} in place of ${view.affected_resource}`}
          />
        )}
      </dl>
    </section>
  )
}

function Line({
  term,
  value,
  emphasis = false,
}: {
  term: string
  value: string
  emphasis?: boolean
}): ReactNode {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-label text-muted uppercase">{term}</dt>
      <dd className={emphasis ? 'text-base font-semibold text-ink' : 'text-ink'}>{value}</dd>
    </div>
  )
}

/**
 * The two buttons.
 *
 * Full-width and stacked, because this is a phone and the two answers are not a toolbar. They
 * carry no icon and no colour-only distinction: the words are the carrier, exactly as they are
 * in the message this page is about.
 *
 * Both are disabled while one is in flight. Not to prevent a duplicate — a second press is
 * already harmless, absorbed by a unique index on the server — but because a page that looked
 * pressable while it was sending would invite somebody to press the *other* one.
 *
 * Above them, when the question closes. The message on their channel names the order's due
 * time and not this one, so without this line a customer is asked for a decision and never told
 * by when. It is the request's own deadline, printed and never compared: whether the window is
 * still open is `answerable`, and that is the server's.
 *
 * Below them, whose decision this is. The change is made only on their yes — that is the whole
 * of the consent protocol, and a page asking for a decision should say so rather than leave it
 * to be inferred from the heading.
 */
function Choice({
  answerBy,
  onAnswer,
  pending,
  failed,
}: {
  answerBy: string | null
  onAnswer: (choice: 'APPROVE' | 'DECLINE') => void
  pending: boolean
  failed: boolean
}): ReactNode {
  return (
    <section className="space-y-3">
      {answerBy === null ? null : (
        <p className="text-sm text-ink" data-testid="answer-by">
          Please answer by {answerBy}.
        </p>
      )}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          disabled={pending}
          onClick={() => {
            onAnswer('APPROVE')
          }}
          className="min-h-12 w-full rounded-control bg-ask px-4 text-base font-semibold text-surface disabled:opacity-60"
        >
          {pending ? 'Sending…' : 'Approve this change'}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => {
            onAnswer('DECLINE')
          }}
          className="min-h-12 w-full rounded-control border border-edge-strong px-4 text-base font-semibold text-ink disabled:opacity-60"
        >
          Decline
        </button>
      </div>
      {/* Declining does not un-spoil an ingredient, so this never promises the original. */}
      <p className="text-xs text-muted">
        We make this change only if you approve it. If you decline, the bakery will follow up
        with you.
      </p>
      {failed ? (
        <p className="text-sm text-owner" role="alert">
          That did not reach the bakery. Nothing was recorded — please try again.
        </p>
      ) : null}
    </section>
  )
}

/** What happened, once there is something true to say about it. */
function Settled({ view }: { view: CustomerApprovalResponse }): ReactNode {
  const answered = formatDateTime(view.answered_at)
  if (view.outcome === null && answered === null) return null
  return (
    <section className="rounded-quiet border border-edge/70 bg-quiet p-4" data-testid="outcome">
      {answered === null ? null : <p className="text-sm text-muted">You answered on {answered}.</p>}
      {view.outcome === null ? null : (
        <p className="mt-1 text-sm text-ink" data-testid="outcome-sentence">
          {view.outcome}
        </p>
      )}
    </section>
  )
}

/** One column, a phone-width gutter, and the mark so the page is recognisably the bakery's. */
function Shell({ children }: { children: ReactNode }): ReactNode {
  return (
    <main className="mx-auto min-h-full w-full max-w-md px-4 py-8">
      <div className="mb-6">
        <PromisePatchLockup height={24} />
      </div>
      {children}
    </main>
  )
}

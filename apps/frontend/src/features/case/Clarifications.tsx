/**
 * What this case asked, and what the worker actually said back.
 *
 * Band 1 is the record of a conversation, not a snapshot of its last turn. Once a question has
 * been answered it leaves `question` — nothing is waiting on it any more — and without this the
 * screen would show a plan whose whole shape depends on an answer that is nowhere on the page.
 * A reader cannot check a decision against an answer they cannot see.
 *
 * Three rules, and each is the reason a field exists on the wire rather than being reassembled
 * here.
 *
 * **The question is quoted, never reconstructed.** `clarifications[].question` is the sentence
 * that was actually asked, stored beside the answer. A screen that rebuilt it from the case's
 * category would be showing a question nobody asked, phrased by whoever wrote the frontend.
 *
 * **The answer is the worker's own words, byte for byte.** It is shown in quotation marks and
 * attributed, because it is an attestation: somebody said it, and the plan below rests on it.
 * It is never summarised, sentence-cased or replaced by the option it resolved to.
 *
 * **The option it resolved to is shown beside the answer, not instead of it.** The code is
 * matched against the options the backend stored with that question, so the label is the one
 * the worker was offered. A code with no matching option shows nothing rather than the code:
 * `LINE-RASP` in front of a person is a token, and the whole point of this panel is words.
 *
 * The open question is somebody else's job. This renders answered turns only, so the one
 * question still waiting keeps the prominence the contract gives it, exactly as before.
 */
import type { ReactNode } from 'react'
import type { ClarificationHistoryView } from '../../api/types'
import { QuietCard } from '../../components/surfaces'
import { Value } from '../../components/values'
import { formatDateTime } from '../../components/time'

export function ClarificationHistory({
  clarifications,
}: {
  clarifications: readonly ClarificationHistoryView[]
}): ReactNode {
  // Answered turns only. The open one is band 1's question card, and showing it twice would
  // read as two questions where the case has exactly one.
  const answered = clarifications.filter((item) => item.answered)
  if (answered.length === 0) return null

  return (
    <ul className="space-y-1.5" data-testid="clarification-history" data-count={answered.length}>
      {answered.map((item) => (
        <li key={item.clarification_id}>
          <AnsweredQuestion item={item} />
        </li>
      ))}
    </ul>
  )
}

/**
 * One exchange, in two lines rather than four.
 *
 * Band 1 is the most crowded region of the workspace and everything below it is the product's
 * actual argument, so this earns its vertical space rather than being given it: the label sits
 * on the question's own line, the attribution sits on the answer's, and the card is as tight as
 * it can be without the quote losing the emphasis that marks it as somebody's own words.
 */
function AnsweredQuestion({ item }: { item: ClarificationHistoryView }): ReactNode {
  const resolved = item.options.find((option) => option.code === item.resolved_option_code)

  return (
    <QuietCard
      className="px-4 py-2"
      data-testid="clarification-answered"
      data-clarification-id={item.clarification_id}
      data-ordinal={item.ordinal}
    >
      <p className="flex flex-wrap items-baseline gap-x-2 text-reason text-muted">
        <span className="text-label uppercase">asked</span>
        {item.question}
      </p>
      {/* A div rather than a paragraph: a blockquote is flow content and a paragraph may hold
          only phrasing, so the browser would close the paragraph before the quote and leave the
          attribution outside the row it belongs to. */}
      <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2.5">
        <blockquote className="text-phrase font-medium text-ink">
          “{item.answer_text}”
        </blockquote>
        <span className="text-label text-muted uppercase">
          <Value>{item.answered_by}</Value>
          {item.answered_at === null ? null : <> · {formatDateTime(item.answered_at)}</>}
          {resolved === undefined ? null : (
            <span data-testid="clarification-resolved"> · read as {resolved.label}</span>
          )}
        </span>
      </div>
    </QuietCard>
  )
}

/**
 * Ingredients and equipment, kept visually separate because they are different kinds of fact.
 *
 * The four ingredient quantities are the engine's own, passed through unchanged. Nothing here
 * recomputes availability, and three properties of the backend's numbers are preserved
 * exactly:
 *
 * - `null` is unknown and is rendered as unknown, never as `0`.
 * - a negative `available_by` is a shortfall and is shown as one, never clamped.
 * - a quantity is displayed as the decimal string the backend sent, never parsed into a
 *   JavaScript number on the way to the screen.
 *
 * Equipment `status` is read from the backend's reading of the outage rows. It is not an
 * answer to "can this task run", which is the engine's, and this panel does not pretend to it.
 */
import type { ReactNode } from 'react'
import type { EquipmentView, IngredientView } from '../../api/types'
import { Badge, QuantityValue, StateBadge, Value } from '../../components/primitives'
import { formatDateTime } from '../../components/time'

const CELL = 'px-3 py-2 align-top'

export function IngredientTable({
  ingredients,
  at,
}: {
  ingredients: readonly IngredientView[]
  at: string
}): ReactNode {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] border-collapse text-sm">
        <caption className="sr-only">
          Ingredient availability computed by {at}. An empty cell is never shown: an unknown
          quantity is labelled unknown.
        </caption>
        <thead>
          <tr className="border-b border-edge bg-surface text-left text-xs font-medium text-muted">
            <th scope="col" className={CELL}>
              Ingredient
            </th>
            <th scope="col" className={`${CELL} text-right`}>
              On hand
            </th>
            <th scope="col" className={`${CELL} text-right`}>
              Expected
            </th>
            <th scope="col" className={`${CELL} text-right`}>
              Reserved
            </th>
            <th scope="col" className={`${CELL} text-right`}>
              Available
            </th>
            <th scope="col" className={CELL}>
              Last posting
            </th>
          </tr>
        </thead>
        <tbody>
          {ingredients.map((ingredient) => (
            <tr
              key={ingredient.id}
              data-testid="ingredient-row"
              data-resource-id={ingredient.id}
              className="border-b border-edge last:border-0"
            >
              <td className={CELL}>
                <div className="font-medium">{ingredient.name}</div>
                <div className="font-mono text-[11px] text-muted">
                  {ingredient.id} · {ingredient.unit}
                </div>
                {ingredient.aliases.length === 0 ? null : (
                  <div className="mt-0.5 text-[11px] text-muted">
                    also called {ingredient.aliases.join(', ')}
                  </div>
                )}
                {ingredient.unknown ? (
                  <div className="mt-1">
                    <Badge tone="bad">unknown supply</Badge>
                  </div>
                ) : null}
                {ingredient.overdue_commitment_line_ids.length === 0 ? null : (
                  <div className="mt-1">
                    <Badge tone="warn">
                      {ingredient.overdue_commitment_line_ids.length} overdue commitment
                    </Badge>
                  </div>
                )}
              </td>
              <td className={`${CELL} text-right`} data-testid="on-hand">
                <QuantityValue value={ingredient.on_hand} />
              </td>
              <td className={`${CELL} text-right`} data-testid="expected">
                <QuantityValue value={ingredient.expected} />
              </td>
              <td className={`${CELL} text-right`} data-testid="reserved">
                <QuantityValue value={ingredient.reserved} />
              </td>
              <td className={`${CELL} text-right`} data-testid="available-by">
                <QuantityValue value={ingredient.available_by} />
              </td>
              <td className={`${CELL} text-[11px] text-muted`}>
                {ingredient.ledger.entries === 0 ? (
                  <span>no postings</span>
                ) : (
                  <>
                    <div>
                      <Value>{formatDateTime(ingredient.ledger.last_recorded_at)}</Value>
                    </div>
                    <div className="font-mono">
                      seq <Value>{ingredient.ledger.last_seq?.toString() ?? null}</Value> ·{' '}
                      <Value>{ingredient.ledger.last_source_kind}</Value>
                    </div>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function EquipmentList({ equipment }: { equipment: readonly EquipmentView[] }): ReactNode {
  return (
    <ul className="divide-y divide-edge">
      {equipment.map((item) => (
        <li
          key={item.id}
          data-testid="equipment-row"
          data-resource-id={item.id}
          className="flex flex-wrap items-start justify-between gap-3 px-4 py-3"
        >
          <div>
            <div className="text-sm font-medium">{item.name}</div>
            <div className="font-mono text-[11px] text-muted">{item.id}</div>
            {item.aliases.length === 0 ? null : (
              <div className="text-[11px] text-muted">also called {item.aliases.join(', ')}</div>
            )}
            {item.scheduled_tasks.length === 0 ? (
              <div className="mt-1 text-[11px] text-muted">nothing scheduled</div>
            ) : (
              <div className="mt-1 text-[11px] text-muted">
                {item.scheduled_tasks.length} task
                {item.scheduled_tasks.length === 1 ? '' : 's'} scheduled
              </div>
            )}
          </div>

          <div className="text-right">
            <StateBadge state={item.status} />
            {item.outages.length === 0 ? null : (
              <ul className="mt-1 space-y-0.5 text-[11px] text-muted">
                {item.outages.map((outage) => (
                  <li key={outage.id}>
                    out from {formatDateTime(outage.starts_at)}{' '}
                    {outage.ends_at === null ? (
                      <span className="font-medium text-red-700">— no end recorded</span>
                    ) : (
                      <>until {formatDateTime(outage.ends_at)}</>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {item.alternative_equipment_ids.length === 0 ? null : (
              <div className="mt-1 text-[11px] text-muted">
                alternatives: {item.alternative_equipment_ids.join(', ')}
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

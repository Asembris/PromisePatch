/**
 * Response payloads shaped exactly like the backend's.
 *
 * Six promises, because the loaded fixture has six, and they are listed here in the order the
 * API returns them — by due time, then external order id. The tests assert that the screen
 * preserves that order rather than imposing one, so the order in this file is part of the
 * fixture and not incidental.
 *
 * The awkward values are deliberate and each one guards a rule the backend documents:
 * a `null` quantity is unknown and must not render as zero; a negative `available_by` is a
 * shortfall and must not be clamped; an outage with no `ends_at` is open-ended; a promise no
 * case has touched carries `null` classification rather than `UNAFFECTED`.
 */
import type { PromisesResponse, PromiseView, ResourcesResponse, WorkerResponse } from '../src/api/types'

export const MAYA: WorkerResponse = {
  worker: {
    id: 'maya',
    username: 'maya',
    display_name: 'Maya',
    role: 'baker',
    may_report: true,
  },
}

function promise(
  id: string,
  externalId: string,
  dueAt: string,
  customer: string,
  recipe: string,
  versionNo: number,
  taskState: string | null,
  overrides: Partial<PromiseView> = {},
): PromiseView {
  return {
    id,
    due_at: dueAt,
    order_id: `or-${id.slice(3)}`,
    external_id: externalId,
    external_version: 1,
    order_state: 'CONFIRMED',
    order_due_at: dueAt,
    customer: { id: `cu-${id.slice(3)}`, name: customer },
    constraints: [],
    lines: [
      {
        id: `ol-${id.slice(3)}`,
        quantity: 1,
        customization_note: '',
        recipe_version: {
          id: `rv-${id.slice(3)}`,
          recipe_id: `rc-${id.slice(3)}`,
          recipe_name: recipe,
          version_no: versionNo,
          authored_by: 'jo',
          authored_at: '2026-08-01T09:00:00Z',
        },
        task:
          taskState === null
            ? null
            : {
                id: `pt-${id.slice(3)}`,
                state: taskState,
                scheduled_start: '2026-09-04T05:00:00Z',
                scheduled_end: '2026-09-04T06:30:00Z',
                equipment_id: 'eq-deck-oven',
                equipment_name: 'Deck oven',
                held_by_case_id: null,
              },
        reservations: [],
      },
    ],
    classification: null,
    track_state: null,
    case_id: null,
    track_id: null,
    ...overrides,
  }
}

export const PROMISES: PromisesResponse = {
  as_of: 41,
  generated_at: '2026-09-04T04:00:00Z',
  promises: [
    promise('pr-a', 'HO-1001', '2026-09-04T07:00:00Z', 'Amara Fell', 'Raspberry Lemon Layer', 2, 'SCHEDULED'),
    promise('pr-b', 'HO-1002', '2026-09-04T08:30:00Z', 'Beatriz Ruiz', 'Berry Tartlets', 3, 'SCHEDULED'),
    promise('pr-c', 'HO-1003', '2026-09-04T09:15:00Z', 'Caleb North', 'Raspberry Coulis Cake', 1, 'STARTED'),
    // Unknown timing is a real state: the task exists but nothing is scheduled yet.
    promise('pr-d', 'HO-1004', '2026-09-04T10:00:00Z', 'Lena Okoye', 'Vanilla Bean Torte', 4, 'PENDING', {
      lines: [
        {
          id: 'ol-d',
          quantity: 2,
          customization_note: 'no nuts',
          recipe_version: {
            id: 'rv-d',
            recipe_id: 'rc-d',
            recipe_name: 'Vanilla Bean Torte',
            version_no: 4,
            authored_by: 'jo',
            authored_at: '2026-08-01T09:00:00Z',
          },
          task: {
            id: 'pt-d',
            state: 'PENDING',
            scheduled_start: null,
            scheduled_end: null,
            equipment_id: null,
            equipment_name: null,
            held_by_case_id: null,
          },
          reservations: [
            {
              id: 'rs-d',
              resource_id: 'in-vanilla',
              resource_name: 'Vanilla bean',
              quantity: null,
              source_recipe_version_id: 'rv-d',
            },
          ],
        },
      ],
    }),
    promise('pr-e', 'HO-1005', '2026-09-04T11:00:00Z', 'Ewan Doyle', 'Almond Croissants', 2, 'SCHEDULED'),
    // The one promise a case has reached, so the case columns have something to prove.
    promise('pr-f', 'HO-1006', '2026-09-04T12:00:00Z', 'Farah Idris', 'Chocolate Ganache Tart', 5, 'SCHEDULED', {
      classification: 'BLOCKED',
      track_state: 'ESCALATED',
      case_id: '4f7c0f8e-0000-4000-8000-000000000001',
      track_id: '4f7c0f8e-0000-4000-8000-000000000002',
    }),
  ],
}

export const RESOURCES: ResourcesResponse = {
  as_of: 41,
  generated_at: '2026-09-04T04:00:00Z',
  at: '2026-09-04T12:00:00Z',
  ingredients: [
    {
      id: 'in-raspberry',
      name: 'Raspberries',
      unit: 'kg',
      aliases: ['razz'],
      on_hand: '0.5',
      expected: '0',
      reserved: '3.2',
      // A shortfall. It must reach the screen as a negative number.
      available_by: '-2.7',
      unknown: false,
      overdue_commitment_line_ids: ['cl-1'],
      ledger: {
        entries: 4,
        last_seq: 40,
        last_recorded_at: '2026-09-04T03:45:00Z',
        last_source_kind: 'ATTESTATION',
        last_source_id: 'at-9',
      },
    },
    {
      id: 'in-vanilla',
      name: 'Vanilla bean',
      unit: 'ea',
      aliases: [],
      // Unknown, not zero.
      on_hand: null,
      expected: null,
      reserved: null,
      available_by: null,
      unknown: true,
      overdue_commitment_line_ids: [],
      ledger: {
        entries: 0,
        last_seq: null,
        last_recorded_at: null,
        last_source_kind: null,
        last_source_id: null,
      },
    },
  ],
  equipment: [
    {
      id: 'eq-deck-oven',
      name: 'Deck oven',
      aliases: ['big oven'],
      status: 'OUT_OF_SERVICE',
      // Open-ended: down, with nobody having said until when.
      outages: [{ id: 'ou-1', starts_at: '2026-09-04T02:00:00Z', ends_at: null }],
      scheduled_tasks: [
        {
          id: 'pt-a',
          order_line_id: 'ol-a',
          state: 'SCHEDULED',
          scheduled_start: '2026-09-04T05:00:00Z',
          scheduled_end: '2026-09-04T06:30:00Z',
        },
      ],
      alternative_equipment_ids: ['eq-convection'],
    },
    {
      id: 'eq-convection',
      name: 'Convection oven',
      aliases: [],
      status: 'IN_SERVICE',
      outages: [],
      scheduled_tasks: [],
      alternative_equipment_ids: [],
    },
  ],
}

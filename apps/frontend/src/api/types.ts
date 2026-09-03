/**
 * The backend contracts, transcribed.
 *
 * These types mirror the Pydantic response models in `promisepatch.api.schemas` field for
 * field. Two conventions from the backend are preserved deliberately rather than smoothed
 * over, because both carry meaning that a friendlier shape would destroy:
 *
 * - **A quantity is a string, or `null`.** The engine's arithmetic is `Decimal`, and it is
 *   serialised as a fixed-point string so that a value cannot change on the way through a
 *   JavaScript number. Parsing one into a `number` here would undo that at the last possible
 *   moment, so quantities are carried and displayed as the strings the backend sent.
 * - **`null` is unknown, and unknown is not zero.** The engine fails closed on an unknown
 *   quantity. Rendering one as `0` would present a promise as satisfiable that the engine
 *   refuses to call satisfiable, so every optional quantity keeps `null` in the type.
 *
 * Timestamps are ISO-8601 strings exactly as received.
 */

/** A decimal quantity in the engine's canonical fixed-point form, or `null` for unknown. */
export type Quantity = string | null

/** The inside of the one error shape this API returns. */
export interface ErrorBody {
  code: string
  message: string
}

export interface ErrorResponse {
  error: ErrorBody
}

// ------------------------------------------------------------------------------------ auth

export interface WorkerIdentity {
  id: string
  username: string
  display_name: string
  role: string
}

export interface WorkerResponse {
  worker: WorkerIdentity
}

// -------------------------------------------------------------------------------- promises

export interface CustomerView {
  id: string
  name: string
}

export interface ConstraintView {
  id: string
  kind: string
  resource_id: string | null
  substitute_resource_id: string | null
  recorded_by: string
  recorded_at: string
}

export interface ReservationView {
  id: string
  resource_id: string
  resource_name: string
  quantity: Quantity
  source_recipe_version_id: string
}

export interface ProductionTaskView {
  id: string
  state: string
  scheduled_start: string | null
  scheduled_end: string | null
  equipment_id: string | null
  equipment_name: string | null
  held_by_case_id: string | null
}

export interface RecipeVersionView {
  id: string
  recipe_id: string
  recipe_name: string
  version_no: number
  authored_by: string
  authored_at: string
}

export interface OrderLineView {
  id: string
  quantity: number
  customization_note: string
  recipe_version: RecipeVersionView
  task: ProductionTaskView | null
  reservations: readonly ReservationView[]
}

export interface PromiseView {
  id: string
  due_at: string
  order_id: string
  external_id: string
  external_version: number
  order_state: string
  order_due_at: string
  customer: CustomerView
  constraints: readonly ConstraintView[]
  lines: readonly OrderLineView[]
  /** `null` when no case has touched this promise. Not a classification of its own. */
  classification: string | null
  track_state: string | null
  case_id: string | null
  track_id: string | null
}

export interface PromisesResponse {
  /** The highest domain event sequence the read transaction could see. */
  as_of: number
  generated_at: string
  promises: readonly PromiseView[]
}

// ------------------------------------------------------------------------------- resources

export interface LedgerPosition {
  entries: number
  last_seq: number | null
  last_recorded_at: string | null
  last_source_kind: string | null
  last_source_id: string | null
}

export interface IngredientView {
  id: string
  name: string
  unit: string
  aliases: readonly string[]
  on_hand: Quantity
  expected: Quantity
  reserved: Quantity
  /** May be negative. A shortfall is a real number and is never clamped to zero. */
  available_by: Quantity
  unknown: boolean
  overdue_commitment_line_ids: readonly string[]
  ledger: LedgerPosition
}

export interface OutageView {
  id: string
  starts_at: string
  /** `null` is open-ended: out of service, with nobody having said until when. */
  ends_at: string | null
}

export interface ScheduledTaskView {
  id: string
  order_line_id: string
  state: string
  scheduled_start: string | null
  scheduled_end: string | null
}

export type EquipmentStatus = 'IN_SERVICE' | 'OUT_OF_SERVICE'

export interface EquipmentView {
  id: string
  name: string
  aliases: readonly string[]
  status: EquipmentStatus
  outages: readonly OutageView[]
  scheduled_tasks: readonly ScheduledTaskView[]
  alternative_equipment_ids: readonly string[]
}

export interface ResourcesResponse {
  as_of: number
  generated_at: string
  /** The horizon the four quantities were computed by. They mean nothing without it. */
  at: string
  ingredients: readonly IngredientView[]
  equipment: readonly EquipmentView[]
}

// ---------------------------------------------------------------------------- event stream

/** One committed domain event, as much of it as a browser is told. */
export interface DomainEventEnvelope {
  seq: number
  id: string
  type: string
  occurred_at: string
  case_id: string | null
  entity_refs: readonly unknown[]
}

/** History was skipped; the client is expected to refetch the read APIs. */
export interface ResyncEnvelope {
  latest_seq: number
  skipped_from_seq: number
  reason: string
  detail: string
}

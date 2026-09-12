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

// ------------------------------------------------------------------------------------ cases

/**
 * The case workspace, transcribed from `promisepatch.api.schemas.cases`.
 *
 * Everything a worker reads is a string the backend composed: `phrase`, `sentence`, `reason`,
 * `next_action` and the band titles all arrive decided. There is no field here a screen is
 * expected to derive, and deriving one — grouping by classification, recounting the untouched,
 * or writing a friendlier word for `RECOVERED` — would put the product's truthful vocabulary in
 * two places, one of which nobody tests against a durable case.
 */

export interface QuestionOptionView {
  code: string
  label: string
}

export interface CaseQuestionView {
  clarification_id: string
  question: string
  options: QuestionOptionView[]
}

export interface NextActionView {
  owner: string
  owner_label: string
  action: string
}

export interface PromiseWorkspaceView {
  promise_id: string
  customer_name: string
  order_external_id: string
  state: string
  phrase: string
  authority: string
  reason: string
  deadline_at: string | null
  owner: string
  next_action: string
  track_id: string
  track_state: string
  classification: string | null
  rule_id: string | null
}

export interface AuthorityBandView {
  authority: string
  title: string
  promises: PromiseWorkspaceView[]
  /** How many promises this authority decides, counted by the backend, never by this list. */
  count: number
}

export interface EffectEvidenceView {
  kind: string
  state: string
  idempotency_key: string
  provider_ref: string | null
  attempts: number
  result: Record<string, unknown> | null
  delivered_at: string | null
  last_error: string | null
}

export interface ApprovalEvidenceView {
  request_id: string
  option_code: string
  state: string
  decided: boolean
  sent_at: string
  deadline: string
  provider_ref: string | null
  decision: string | null
  parser: string | null
  replies: number
}

export interface RevalidationCheckView {
  index: number
  name: string
  passed: boolean
  expected: string
  actual: string
}

export interface RevalidationEvidenceView {
  outcome: string
  deciding_check: number | null
  detail: string | null
  fingerprint: string | null
  checks: RevalidationCheckView[]
}

export interface TrackEvidenceView {
  promise_id: string
  track_id: string
  track_state: string
  classification: string | null
  rule_id: string | null
  reason_detail: string | null
  fingerprint: string | null
  order_external_id: string
  order_external_version: number
  mirrored_versions: Record<string, string>
  paths: number
  watched_entities: number
  effects: EffectEvidenceView[]
  approval: ApprovalEvidenceView | null
  revalidation: RevalidationEvidenceView | null
}

export interface InterpretationEvidenceView {
  source: string
  outcome: string | null
  attestor: string | null
  step_state: string | null
  provider: string | null
  model_id: string | null
  deterministic_reason: string | null
  grounded: string[]
  rejected: string[]
  failure: string | null
  last_error: string | null
}

export interface EvidenceView {
  case_id: string
  case_state: string
  case_version: number
  plan_id: string
  exception_id: string | null
  interpretation: InterpretationEvidenceView | null
  tracks: TrackEvidenceView[]
}

export interface CaseWorkspaceResponse {
  case_id: string
  headline: string
  sentence: string
  exception_category: string | null
  reported_text: string | null
  reported_by: string | null
  reported_at: string | null
  needs_owner_attention: boolean
  question: CaseQuestionView | null
  next_action: NextActionView
  authority_bands: AuthorityBandView[]
  untouched: PromiseWorkspaceView[]
  untouched_count: number
  threatened_count: number
  /** Every promise the case considered. The denominator; never `untouched + threatened` here. */
  promise_count: number
  plan_id: string | null
  awaiting_confirmation: boolean
  evidence: EvidenceView
}

export interface CaseSummaryView {
  case_id: string
  state: string
  headline: string
  sentence: string
  needs_owner_attention: boolean
  reported_text: string | null
  opened_at: string
  updated_at: string
}

export interface CaseListResponse {
  cases: CaseSummaryView[]
}

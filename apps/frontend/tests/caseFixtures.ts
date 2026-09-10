/**
 * The canonical case, in the three shapes the workspace has to render.
 *
 * Every string here is one the backend actually produces for the Hollow Oak fixture at the
 * corresponding step of the canonical path — the phrases, reasons, rule ids and next actions
 * are copied from `promisepatch.domain.status_view`, not invented, so a test asserting on a
 * phrase is asserting on the vocabulary the product really uses.
 *
 * `SETTLED_CASE` is the important one. It holds one promise the order system confirmed, one
 * customer who has been asked, one the owner must handle by hand, and two nothing was done to.
 * A screen that blurs any of those four into another is the failure these fixtures exist to
 * catch, and the four are deliberately given different phrases so a blur is visible.
 */
import type {
  CaseListResponse,
  CaseWorkspaceResponse,
  EvidenceView,
  PromiseWorkspaceView,
} from '../src/api/types'

export const CASE_ID = '2b3fc0e0-1f52-4b8f-9a1e-6d1f0f7c9a11'

function workspacePromise(
  promiseId: string,
  externalId: string,
  customer: string,
  overrides: Partial<PromiseWorkspaceView> = {},
): PromiseWorkspaceView {
  return {
    promise_id: promiseId,
    customer_name: customer,
    order_external_id: externalId,
    state: 'PLANNED',
    phrase: 'planned - waiting for you',
    authority: 'STANDING_PREFERENCE',
    reason: 'PREAPPROVAL_COVERS',
    deadline_at: null,
    owner: 'YOU',
    next_action: 'Read the plan and confirm it, or leave it as it is.',
    track_id: `track-${promiseId}`,
    track_state: 'PENDING',
    classification: 'AUTO_RECOVERABLE',
    rule_id: 'R-PREAPPROVED',
    ...overrides,
  }
}

function untouched(promiseId: string, externalId: string, customer: string): PromiseWorkspaceView {
  return workspacePromise(promiseId, externalId, customer, {
    state: 'UNTOUCHED',
    phrase: 'left alone',
    authority: 'NONE',
    reason: 'NOT_REACHABLE',
    owner: 'NOBODY',
    next_action: 'Nothing. This promise is not reachable from what happened.',
    track_state: 'UNAFFECTED',
    classification: 'UNAFFECTED',
    rule_id: 'R-UNREACH',
  })
}

const UNTOUCHED_PROMISES: PromiseWorkspaceView[] = [
  untouched('pr-e', 'EXT-E', 'Ahmed Bouazizi'),
  untouched('pr-f', 'EXT-F', 'Cafe Marlow'),
]

const PLANNED_EVIDENCE: EvidenceView = {
  case_id: CASE_ID,
  case_state: 'PLANNED',
  case_version: 4,
  plan_id: 'ac1f2b3c4d5e6f70',
  exception_id: '9d0b1f2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f',
  interpretation: {
    source: 'DETERMINISTIC',
    outcome: 'RESOLVED',
    attestor: 'maya',
    step_state: 'DONE',
    provider: null,
    model_id: null,
    deterministic_reason: null,
    grounded: [],
    rejected: [],
    failure: null,
    last_error: null,
  },
  tracks: [
    {
      promise_id: 'pr-a',
      track_id: 'track-pr-a',
      track_state: 'PENDING',
      classification: 'AUTO_RECOVERABLE',
      rule_id: 'R-PREAPPROVED',
      reason_detail: 'PREAPPROVAL_COVERS',
      fingerprint: 'fp-a0011223344556677',
      order_external_id: 'EXT-A',
      order_external_version: 1,
      mirrored_versions: { 'ol-a': 'rv-raspberry-almond-3' },
      paths: 2,
      watched_entities: 3,
      effects: [],
      approval: null,
      revalidation: null,
    },
  ],
}

export const PLANNED_CASE: CaseWorkspaceResponse = {
  case_id: CASE_ID,
  headline: 'PLANNED',
  sentence: 'Planned, and waiting for you. Nothing has been done yet.',
  exception_category: 'DELIVERY_SHORTFALL',
  reported_text: 'today’s raspberry delivery didn’t arrive',
  reported_by: 'maya',
  reported_at: '2026-03-04T07:05:00+00:00',
  needs_owner_attention: false,
  question: null,
  next_action: {
    owner: 'YOU',
    owner_label: 'You',
    action: 'Read the plan below and confirm it before anything is done.',
  },
  authority_bands: [
    {
      authority: 'STANDING_PREFERENCE',
      title: 'Covered by a standing preference',
      promises: [workspacePromise('pr-a', 'EXT-A', 'Priya Nair')],
    },
    {
      authority: 'CUSTOMER',
      title: 'Needs the customer',
      promises: [
        workspacePromise('pr-b', 'EXT-B', 'Tomas Lindqvist', {
          authority: 'CUSTOMER',
          reason: 'VISIBLE_CHANGE_ASK',
          classification: 'APPROVAL_REQUIRED',
          rule_id: 'R-VISIBLE-ASK',
        }),
      ],
    },
    {
      authority: 'OWNER',
      title: 'Needs the owner',
      promises: [
        workspacePromise('pr-c', 'EXT-C', 'Okafor-Reyes wedding', {
          authority: 'OWNER',
          reason: 'NOSUB_CONSTRAINT',
          classification: 'BLOCKED',
          rule_id: 'R-NOSUB',
        }),
      ],
    },
  ],
  untouched: UNTOUCHED_PROMISES,
  untouched_count: 2,
  threatened_count: 3,
  plan_id: 'ac1f2b3c4d5e6f70',
  awaiting_confirmation: true,
  evidence: PLANNED_EVIDENCE,
}

export const SETTLED_CASE: CaseWorkspaceResponse = {
  ...PLANNED_CASE,
  headline: 'WAITING',
  sentence: 'Waiting on a customer to answer.',
  needs_owner_attention: true,
  next_action: {
    owner: 'OWNER',
    owner_label: 'The owner',
    action:
      '1 promise below needs the owner by hand. Nothing will change until somebody picks them up.',
  },
  plan_id: null,
  awaiting_confirmation: false,
  authority_bands: [
    {
      authority: 'STANDING_PREFERENCE',
      title: 'Covered by a standing preference',
      promises: [
        workspacePromise('pr-a', 'EXT-A', 'Priya Nair', {
          state: 'RECOVERED',
          phrase: 'changed',
          owner: 'NOBODY',
          next_action: 'Nothing. The order system carries the change.',
          track_state: 'RECOVERED',
        }),
      ],
    },
    {
      authority: 'CUSTOMER',
      title: 'Needs the customer',
      promises: [
        workspacePromise('pr-b', 'EXT-B', 'Tomas Lindqvist', {
          state: 'REQUESTED',
          phrase: 'asked',
          authority: 'CUSTOMER',
          reason: 'VISIBLE_CHANGE_ASK',
          deadline_at: '2026-03-04T10:05:00+00:00',
          owner: 'CUSTOMER',
          next_action:
            'Nothing. The customer has been asked and has not answered by 2026-03-04T10:05:00+00:00.',
          track_state: 'WAITING_FOR_CUSTOMER',
          classification: 'APPROVAL_REQUIRED',
          rule_id: 'R-VISIBLE-ASK',
        }),
      ],
    },
    {
      authority: 'OWNER',
      title: 'Needs the owner',
      promises: [
        workspacePromise('pr-c', 'EXT-C', 'Okafor-Reyes wedding', {
          state: 'ESCALATED',
          phrase: 'needs you',
          authority: 'OWNER',
          reason: 'NOSUB_CONSTRAINT',
          owner: 'OWNER',
          next_action: 'The owner handles this one by hand. Nothing will change until they do.',
          track_state: 'ESCALATED',
          classification: 'BLOCKED',
          rule_id: 'R-NOSUB',
        }),
      ],
    },
  ],
  evidence: {
    ...PLANNED_EVIDENCE,
    case_state: 'WAITING',
    tracks: [
      {
        ...PLANNED_EVIDENCE.tracks[0]!,
        track_state: 'RECOVERED',
        effects: [
          {
            kind: 'ORDER_AMEND',
            state: 'DELIVERED',
            idempotency_key: 'pp:amend:track-pr-a:opt:1',
            provider_ref: 'amd-58ad55e82e28',
            attempts: 1,
            result: { external_version: 2 },
            delivered_at: '2026-03-04T07:06:00+00:00',
            last_error: null,
          },
        ],
      },
      {
        promise_id: 'pr-e',
        track_id: 'track-pr-e',
        track_state: 'UNAFFECTED',
        classification: 'UNAFFECTED',
        rule_id: 'R-UNREACH',
        reason_detail: 'NOT_REACHABLE',
        fingerprint: null,
        order_external_id: 'EXT-E',
        order_external_version: 1,
        mirrored_versions: { 'ol-e': 'rv-dark-chocolate-ganache-5' },
        paths: 0,
        watched_entities: 0,
        effects: [],
        approval: null,
        revalidation: null,
      },
    ],
  },
}

/** The same case mid-flight: accepted by the order system, not yet observed to have landed. */
export const APPLYING_CASE: CaseWorkspaceResponse = {
  ...SETTLED_CASE,
  headline: 'WORKING',
  sentence: 'Carrying out what you confirmed.',
  next_action: {
    owner: 'OWNER',
    owner_label: 'The owner',
    action:
      '1 promise below needs the owner by hand. Nothing will change until somebody picks them up.',
  },
  authority_bands: SETTLED_CASE.authority_bands.map((band) =>
    band.authority === 'STANDING_PREFERENCE'
      ? {
          ...band,
          promises: [
            workspacePromise('pr-a', 'EXT-A', 'Priya Nair', {
              state: 'APPLYING',
              phrase: 'changing the order now',
              owner: 'SYSTEM',
              next_action:
                'Nothing. The order change has gone out and is not confirmed yet.',
              track_state: 'APPLYING',
            }),
          ],
        }
      : band,
  ),
}

export const CLARIFYING_CASE: CaseWorkspaceResponse = {
  ...PLANNED_CASE,
  headline: 'CLARIFYING',
  sentence: 'Waiting for your answer before anything is decided.',
  question: {
    clarification_id: '7c8d9e0f-1a2b-4c3d-8e4f-5a6b7c8d9e0f',
    question: 'Which of them did not arrive?',
    options: [
      { code: 'A', label: 'Only the raspberries' },
      { code: 'B', label: 'The whole delivery' },
    ],
  },
  next_action: {
    owner: 'YOU',
    owner_label: 'You',
    action: 'Answer the question above, in your own words.',
  },
  authority_bands: [],
  untouched: [],
  untouched_count: 0,
  threatened_count: 0,
  plan_id: null,
  awaiting_confirmation: false,
}

export const CASES: CaseListResponse = {
  cases: [
    {
      case_id: CASE_ID,
      state: 'PLANNED',
      headline: 'PLANNED',
      sentence: 'Planned, and waiting for you. Nothing has been done yet.',
      needs_owner_attention: false,
      reported_text: 'today’s raspberry delivery didn’t arrive',
      opened_at: '2026-03-04T07:05:00+00:00',
      updated_at: '2026-03-04T07:05:30+00:00',
    },
  ],
}

export const NO_CASES: CaseListResponse = { cases: [] }

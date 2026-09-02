# ADR-0003 — Custom persisted state machine and worker

Status: accepted
Date: 2026-09-02
Phase: 2

## Decision

The durable case workflow is a transition table in code over case and track rows in Postgres,
with a step ledger, a `timers` table, inbox/outbox tables, and a `worker` process that
performs boot recovery.

## Context

The frozen case state machine has re-entrant loops (stale re-planning), per-track sub-states,
and exit events arriving from three different sources. The demo has to show a real process
restart losing nothing.

## Alternatives rejected

- **AWS Step Functions** — splits the logic into ASL and makes local testing an emulator
  exercise; loops and per-track re-planning are awkward to express.
- **Temporal** — a second server to operate locally and in AWS, and it hides the durability
  story the demo exists to prove.
- **AgentCore Memory / runtime sessions** — conversation-scoped, not case-scoped, and rejected
  by the product specification.

## Why

Full control of the frozen machine, single-store atomicity, identical behaviour locally and in
AWS, and a machine that can be model-tested with Hypothesis.

## Consequences

Restart safety becomes a property of the tables rather than of any process.

## Revisit trigger

A second bakery, or horizontal worker scaling — then reassess Temporal.

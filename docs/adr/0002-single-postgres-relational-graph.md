# ADR-0002 — Single PostgreSQL store, relational graph

Status: accepted
Date: 2026-09-02
Phase: 1

## Decision

All authoritative state — the promise graph, case state, step ledger, inbox/outbox and the
audit ledger — lives in one PostgreSQL database. Graph edges are derived from foreign keys
plus role columns, not stored in a generic edge table.

## Context

The graph is roughly fifty nodes and is tightly coupled to the state transitions that read it.
Its invariants need real constraints and real transactions: one live track per promise, a
governed write that cannot commit without its audit row, exactly-once physical postings.

## Alternatives rejected

- **Neo4j or another graph database** — a second store breaks atomicity between the graph and
  the case state that depends on it, for a graph small enough to walk in memory.
- **DynamoDB** — no partial unique indexes, and transaction size limits below what the
  invariants need.
- **Aurora** — cost and operational complexity not earned at this scale.

## Why

Atomic transitions, audit and outbox in one commit; partial unique indexes enforce invariants
the application would otherwise only promise.

## Consequences

The engine never sees ORM objects: a loader builds an immutable `GraphSnapshot` from the
database, and every deterministic decision runs against that. Phase 0 exercises the engine
side of that boundary with hand-built snapshots and no database at all.

## Revisit trigger

More than 10^4 nodes, or multi-tenant scale. Neither is in scope.

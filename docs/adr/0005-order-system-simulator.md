# ADR-0005 — Order system: labelled simulator canonical, Square adapter optional

Status: accepted
Date: 2026-09-02
Phase: 3

## Decision

A clearly labelled **External Order System — simulator** (its own process, port, window title
and storage) is the system of record for the demo. A Square Sandbox adapter behind the same
`OrderSystemPort` remains optional upside.

## Context

Proof A requires an order mutation made *outside* PromisePatch and ingested through a change
event, on camera, inside a three-minute video. Square Sandbox Dashboard line-item editing is
undocumented and the dashboard is a limited subset of the production one.

## Alternatives rejected

- **Square only** — puts an unverified on-camera mutation path on the critical path of the
  demo.
- **An order editor inside PromisePatch** — forbidden by the product specification; the whole
  point of Proof A is that the change originates elsewhere.

## Why

Honesty and reliability of Proof A, with an identical event contract that keeps the Square
door open.

## Consequences

The simulator must look unmistakably like a separate system, or a judge may read it as a
hidden PromisePatch editor. It never shares code or a database with PromisePatch.

## Revisit trigger

A verified Sandbox Dashboard line-item edit with a webhook round trip under five seconds,
before the Phase 9 gate.

# CLAUDE.md — PromisePatch operating contract

## Purpose

PromisePatch turns one spoken physical-world exception ("today's raspberry delivery didn't
arrive") into a correct, consent-respecting, selectively-applied set of customer-promise
recoveries, with the reasoning visible. Made-to-order bakery vertical.

## Current state

Deterministic engine, backend foundation, and PostgreSQL baseline schema are complete. Next
work is the database audit, immutability, and least-privilege runtime boundary.

## Authoritative documents

`PROMISEPATCH_PRODUCT_SPEC.md` and `ARCHITECTURE_PLAN.md` are frozen, gitignored, local-only
and **authoritative whenever present**. Read them before deciding anything they cover. Never
modify them unless explicitly asked. Never commit them.

## Core rule

**The model understands; the deterministic protocol authorizes.**

## Key invariants

- The LLM never authorizes a write and never produces a consent decision.
- Customer consent is only a literal `YES` / option code / `NO`; free text is at most a
  non-authoritative apparent intent that can trigger one confirmation prompt.
- Recovery selects only pre-authored `RecipeVersion`s named by `SubstitutionPolicy`. Nothing
  at runtime creates, derives or synthesizes a version.
- The external order system is the system of record for orders. PromisePatch has no order
  editor; it writes to an order only as a governed recovery amendment.
- Physical facts (received / not received / spoiled / equipment out) are authoritative
  independently of recovery authorization. Declining a plan never un-spoils anything; only an
  explicit correcting attestation reverses a fact.
- A commitment line is open (`EXPECTED`) or settled. Settlement posts its physical outcome to
  the ledger exactly once, and a settled line contributes zero to expected supply. Received
  supply is never also counted as expected.
- Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
  `AUTO_RECOVERABLE`.
- Promises not reachable from the exception are untouched: no message, no write, no
  reservation change, no task hold, no audit event.

## Architecture summary

One Python backend (`api`, `worker`, `mcp` entrypoints), one pure engine package
(`promise_graph`), one React evidence UI, one separate External Order System simulator,
PostgreSQL as the single store, a persisted case state machine with a step ledger, Bedrock for
understanding only, MCP for the five intent tools, Telegram for the customer channel.
`promise_graph` depends on the standard library and Pydantic only, does no I/O, reads no
environment, and never calls the wall clock — time is passed in explicitly.

## Development rules

- One phase at a time. Never build Phase N+1 artifacts while in Phase N.
- Do not redesign frozen architecture; amend the ADR first if a decision must change.
- All gates must pass before a phase is complete: pytest with the coverage floor, the
  Hypothesis CI profile, mypy, ruff check, ruff format, import-linter.
- Never weaken, skip or delete a test to make code pass. Fix the code or fix the fixture data
  and say so.
- Secrets are never committed. No `.env`, no tokens, no credentials.
- No synthetic validation, no invented metrics, no performance or impact claims.

## Git

One-line Conventional Commit subjects. No body, no bullets, no trailers, no co-author line,
no generated-by line, no emoji. Example: `feat(engine): propagation`.
Never push unless explicitly asked.

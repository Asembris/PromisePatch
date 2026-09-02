# ADR-0001 — Backend stack

Status: accepted
Date: 2026-09-02
Phase: 0

## Decision

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, PostgreSQL 16, and a `uv`
workspace with `packages/promise-graph` as the first member.

## Context

One language has to carry the deterministic engine, the durable workflow, the MCP server, the
evaluation harness and the infrastructure code. The engine's correctness story rests on
property-based testing, and Hypothesis is the strongest option available in any of the
candidate languages.

## Alternatives rejected

- **TypeScript backend** — would split the engine's language from its testing story and add a
  second toolchain for no product gain.
- **Django** — its ORM and admin are unused, and it is sync-first where the STT relay and live
  feed want async.

## Why

Strongest testing story for the deterministic core; first-class AWS and MCP SDKs; a single
language from engine to IaC.

## Consequences

Phase 0 uses only the Python 3.12 + Pydantic + `uv` parts of this decision. FastAPI,
SQLAlchemy, Alembic and PostgreSQL are introduced in Phase 1 and are deliberately absent from
the workspace until then.

## Revisit trigger

None expected within the hackathon.

# ADR-0004 — One Bedrock model via Converse forced tool-use

Status: accepted — amended by [ADR-0007](0007-runtime-semantic-model-nova-2-lite.md),
which replaces the model identity below with `us.amazon.nova-2-lite-v1:0`. Everything
else on this page still stands: one model for every job, Converse with forced tool use,
schema validation, one corrective retry, deterministic fallback, no write tool.
Date: 2026-09-02
Phase: 4

## Decision

A single model, `claude-haiku-4-5`, through a cross-Region inference profile, called with the
boto3 `bedrock-runtime` Converse API and forced tool-use for structured output. Every output
is validated against a Pydantic schema, with one corrective retry and a deterministic
fallback. `claude-sonnet-5` is the configured escalation.

## Context

The model does five jobs: utterance interpretation, clarification phrasing, plan and status
verbalisation, customer-message drafting, and closed-label reply classification. All are
latency-sensitive because they sit in a spoken turn, and none of them decides anything.

## Alternatives rejected

- **Multi-model routing** — unjustified complexity for five closed-label jobs.
- **Nova Sonic speech-to-speech** — a bidirectional stream gives weaker control of the
  one-clarification protocol and is harder to evaluate.
- **A second SDK surface** — one client, one prompt suite, one eval suite.

## Why

Lowest-latency Claude tier for voice turns; forced tool-use yields schema-shaped JSON.

## Consequences

The model holds no write tool and never produces a consent decision. Nothing in
`packages/promise-graph` knows the model exists, which is why Phase 0 runs with zero cloud
access.

## Revisit trigger

Grounding below 95% or JSON validity below 99% in the eval suites — switch to Sonnet 5 by
environment variable.

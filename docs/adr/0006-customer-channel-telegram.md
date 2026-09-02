# ADR-0006 — Customer channel: Telegram Bot API canonical

Status: accepted
Date: 2026-09-02
Phase: 6

## Decision

The canonical customer channel is the Telegram Bot API: an HTTPS webhook verified by a
`secret_token` header, `update_id` deduplication, and the numeric chat id as the customer's
approval identity. AWS End User Messaging Social (WhatsApp) sits behind the same
`MessagingProvider` port as an optional production adapter. A `console` provider serves local
development and CI. Twilio is removed from the MVP entirely.

## Context

Proof E is the most distinctive part of the demo and must not sit behind an approval queue
owned by a third party. WhatsApp Business onboarding requires a Meta Business account, a phone
number not already on WhatsApp, display-name review and template approval — all with unbounded
external latency. AWS two-way SMS needs an in-country dedicated number, which is unavailable
from Tunisia. Email weakens the literal parser because clients quote the original message.

## Alternatives rejected

- **WhatsApp as canonical** — an external approval gate on the critical path.
- **AWS SMS** — no in-country two-way number available.
- **SES two-way email** — quoted replies make literal parsing fragile.
- **Twilio** — a paid third-party dependency offering nothing Telegram does not.

## Why

Free, set up in minutes, a real app on a real second device, a plain HTTPS webhook with a
shared secret, provider-side retry that the inbox already deduplicates, and no template
gating — so the two-message consent thread is fast and reliable on camera.

## Consequences

The customer must press Start on the bot once before the demo, because bots cannot initiate
conversations. This is a rehearsed setup step, verified by `pp channel check`, and is directly
analogous to the WhatsApp opt-in it replaces. Every clause of the frozen consent contract —
external device, independent provider, asynchronous webhook, literal-only decisions — is
satisfied unchanged.

## Revisit trigger

A judge or production customer specifically requiring WhatsApp: enable the EUM Social adapter,
one environment value, no engine change.

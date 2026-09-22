# The message stopped lying, and the address stopped leaving

Date: 2026-09-22, after [`deployed-customer-channel.md`](deployed-customer-channel.md) section
11 and in a separate session. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything was
read and again before anything was mutated.

Two defects the first real customer loop exposed, both closed, both deployed. A third thing was
reconciled on the way: the host's `converge.sh`, stale since 2026-09-18, is now the committed
one.

Neither defect was a correctness bug. The consent protocol, the literal parser, the signed link,
the ten revalidation checks and ADR-0018's separation of worker approval from customer consent
are all exactly as they were. What moved is one sentence a customer reads and one set of render
boundaries an operator reads.

## 1. What was wrong, measured rather than supposed

**The message told the customer to do something impossible.** §13.6 froze the reply instruction
as *"Reply YES to approve this change or NO to decline it."*, and that sentence presupposes an
inbound channel this build deliberately does not have. On 2026-09-22 a real person, holding a
real approval message, typed a literal `YES` into the bot's own chat because the message told
them to. It reached nothing: `inbound_replies` 0, `approval_decisions` 0, the request still
`SENT`, and not one `getUpdates` call in the deployment's entire history. Section 10.7 of
[`deployed-customer-channel.md`](deployed-customer-channel.md) records it.

**A real person's Telegram chat id was being read out on five surfaces.** Sections 10.8 and 11.7
named two of them. An audit for this work found three more, and two of those are public.

| # | boundary | carried it as | previously recorded |
|---|---|---|---|
| 1 | `worker.telegram.sent` → CloudWatch | `chat_id` field **and** inside `provider_ref` | yes, §10.8 |
| 2 | `pp case-status` | `approval.provider_ref`, `effect.provider_ref` | yes, §11.7 |
| 3 | `pp case-status` | revalidation check 8's `expected` / `actual` (`tg:<id>`) | **no** |
| 4 | `GET /api/cases/{id}` | the same three fields, **over the public internet** | **no** |
| 5 | the deployed SPA's evidence drawer | `Evidence.tsx` rendered `provider_ref` verbatim | **no** |
| 6 | `pp channel check` | echoed the chat id back to the terminal | **no** |

4 and 5 are the serious ones: anyone holding a case id could read a real customer's Telegram
identifier from `https://184.194.40.87.sslip.io`. The `ApprovalEvidenceView` docstring said *"No
channel, no reply text"* while `provider_ref` carried the channel, and
`analysis.ApprovalStatus`'s said *"Deliberately without the customer's channel address"* while
doing the same. Both docstrings described the intended design; the code had quietly stopped
keeping it.

## 2. What was decided

[ADR-0021](adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md),
which amends §13.6's frozen literal and states the disclosure boundary. The two headline rules:

- **The instruction names the link, because the link is the only door.** Telegram inbound stays
  unbuilt — a second route for the word `YES` would be a second consent parser. The correct
  response to "the customer replied on Telegram and nothing happened" is to stop telling them
  to, not to start listening.
- **The address is masked where it is read out, and kept where it is used.** The outbox row, the
  approval request, the decision row and the audit ledger keep it whole; a log, a terminal, an
  HTTP response and a rendered page get the channel kind and nothing else.

**Masking rather than hashing, and the reason is arithmetic.** A Telegram chat id is about ten
decimal digits, so the space is roughly ten billion and a truncated digest of one is a digest a
commodity GPU walks through in seconds. `sha256(chat_id)` would have published the chat id to
anybody who cared while looking careful. A keyed digest was rejected separately: a key reaching
every rendering boundary is a second secret to hold, rotate and leak, bought for an operator
convenience that the idempotency key already provides.

## 3. What was built

`promisepatch.domain.disclosure` — pure, no I/O, no clock, no settings — with two functions.
`redact_channel` reduces `telegram:<id>:<msg>` and `tg:<id>` to `telegram:***` and `tg:***`,
and returns anything it does not recognise unchanged, so `amd-e735e9398046`, `fake-…` and
`link:<uuid>` survive intact. `redact_comparison` handles check 8, whose evidence *is* a pair of
addresses: it takes the check's own verdict rather than comparing the two strings, because check
8's right-hand side is the sender *and* the chain it was followed back to, so a passing check's
two sides are never equal as text.

**It is applied in one place, not six.** `promisepatch.domain.analysis` is the single projection
the CLI, the HTTP response and the SPA are all built from, so masking there closed boundaries 2,
3, 4 and 5 together. Boundary 1 is the one log call in the adapter; boundary 6 is one line in the
CLI, now matching `bind-demo-customer`, which had always refused to echo.

The prefix list is declared in `disclosure` rather than imported, because the import contracts
forbid `promisepatch.integrations` both `promisepatch.db` and `promisepatch.graph` — a helper
the adapter could not call would not cover the log line it was written for. `test_disclosure.py`
asserts the set against both real vocabularies, so the duplication is checked rather than
trusted.

### The copy, exactly

| | before | after |
|---|---|---|
| `CONSENT_INSTRUCTION` | Reply YES to approve this change or NO to decline it. If you decline, the bakery will follow up. | **Open the secure link below to approve or decline this change.** If you decline, the bakery will follow up. |
| `CONFIRMATION_INSTRUCTION` | To confirm this change, reply YES. Reply NO to decline. | **To approve or decline this change, use the secure link in our earlier message.** |

The decline clause is §13.6's own and is reproduced exactly. The confirmation sentence points
**backwards** rather than at a line below it, and that is not style: the confirmation prompt's
effect payload carries no `approval_url` — only the approval request's does — so "the link
below" would have named a line the transport was never given anything to write. That is the same
defect in a new spelling, and it was caught before it shipped.

**A deployment that mints no link now asks for nothing at all.** Where
`PP_CUSTOMER_LINK_SECRET` is unset there is no surface on which a customer could answer, so the
message stops being a question: *"This message cannot take your answer, so nothing about your
order changes because of it. The bakery will follow up."* Both claims hold by construction — no
consent means no amendment, and an unanswered request reaches its deadline and escalates the
promise to its owner. The wording and the link are chosen from **one** reading of one setting,
and `carries_required_literals` is told which sentence was owed, so a message promising a link
nobody attached fails the guard rather than being sent.

Refusing to send at all in that configuration would arguably follow from §13.6's own principle —
*a request is never sent into a window in which no valid answer could arrive*. It is a state
machine change rather than a wording change and was **not** taken. ADR-0021 decision 3 records
it as declined, not overlooked.

## 4. Tests

`test_disclosure.py` is new: the reduction in both vocabularies, the closed prefix list checked
against `db.types.CHANNEL_KINDS` and `graph.channel.PREFIX_BY_KIND`, `None` passing through as
`None` so "no reference" and "a withheld reference" stay different facts, and check 8's three
cases — matched, differed, and nobody answered.

The regression that matters most is in `test_customer_approval.py` and is asserted on the real
outbox payload rather than on a builder:

```python
promises_a_link = messaging.CONSENT_INSTRUCTION in text
carries_a_link = bool(payload.get("approval_url"))
assert promises_a_link is carries_a_link
```

An equivalence rather than a value, so it holds however the environment running it is
configured, and it fails the moment the wording and the link stop agreeing. Beside it,
`test_a_customers_chat_id_never_reaches_the_status_projection` drives a real case through a
provider that stamps `telegram:<chat>:<msg>` the way the live adapter does — the suite otherwise
runs entirely on `fake-<hex>` references, which carry no address and so could never have caught
this — and asserts the projection masks it **and** that the row underneath still holds it whole.

`test_telegram_channel.py` gained the log assertion, captured from stdout rather than through
`caplog`, because the renderer is what a log group receives and a test reading the stdlib record
would assert about a string nobody ships.

**One existing assertion was changed rather than satisfied, and it is named here.**
`test_customer_intent.py` forbade the word `approve` in the confirmation prompt — a proxy for
"no anchor toward either answer" that worked only while the prompt had no reason to say it.
ADR-0021's prompt offers both choices by name, so the proxy was replaced with the rule it stood
for, asserted directly and more tightly: `text.count("approve") == text.count("decline")`.
Two hard-coded frozen literals in `test_consent_parser.py` and `test_customer_intent.py` were
updated to the new sentences, which is the point of pinning a customer-facing literal — the next
change to it is also deliberate.

## 5. The host's `converge.sh`, reconciled

Section 8.7 recorded the consequence and sections 10.8 and 11.7 repeated it: the host's
`converge.sh` was the pre-channel one, so `env/channel.env` was hand-written rather than derived,
and a rotated bot token would not have been picked up until the migration was re-run or the host
replaced. That is now closed, **without replacing the host, reseeding anything, changing IAM or
passing a secret through an operator's shell.**

The committed script is inside a *quoted* heredoc (`<<'CONVERGE'`) in the template's `UserData`,
so its content is literal: no `Fn::Sub` substitution reaches it and no bootstrap value is baked
into it. Every value it uses comes from `env/host.env`, already on the host, and from SSM through
the instance role. That is what makes it reproducible from the template alone.

**The extraction was proved before it was trusted.** The same extractor run against the template
at `01174e3^` — the commit before the channel block — produced 910 bytes hashing to
`45f5145e418ea4b6973cffcc469b69b76c176d87a81d3835bd2cb255c778188a`, which is byte-for-byte the
file that was on the host. Applied to `HEAD` it produces 2416 bytes hashing to
`09105b1001184df4b26a2fc8a06581c62c38f20c6a72389d911a5e5258eefe9c`. The diff between them is
**purely additive**: 26 lines inserted, nothing removed and nothing altered.

**Then the block was proved before it was installed.** The committed channel block was run on the
host writing to a temp path instead of `env/channel.env`, and compared:

```text
identity   arn:aws:sts::265243686715:assumed-role/PromisePatchInstanceRole/i-087c742587f83d61d
probe      c3a6e4dea3f37c58707db90c2690fb1ab3ee2f51b6d123ad47b4307922225240  232
live       c3a6e4dea3f37c58707db90c2690fb1ab3ee2f51b6d123ad47b4307922225240  232
IDENTICAL
```

The identity that read the two secrets is the *host's own instance role*. Only the non-secret
provider value was echoed. The probe was deleted.

The script was then installed with the old one kept beside it as `converge.sh.bak-20260922`,
ownership and mode preserved at `root root 0750`. **The reboot below is what exercised it**, and
section 6 records the proof.

## 6. The release, performed

`./deploy/deploy.sh images` → `config` → *(see below)* → `rollout` → `smoke`, at
`4cfb74de7cc2`, tracked tree clean.

### 6.1 Why `stack` could not carry it, and what did

`deploy.sh stack` **refused**, correctly:

```text
error: this release would replace or remove: ElasticIpAssociation	Host.
A release moves the image tag and nothing else, so the change set was deleted
unexecuted and nothing was mutated.
```

[`non-destructive-release.md`](non-destructive-release.md) §10.1 predicted this exactly: the
deployed stack's template predates `01174e3`, so submitting this checkout's template edits
`Host.UserData` and CloudFormation answers `Replacement: Conditional`. The guard counts
`Conditional` with `True`. **That refusal is correct and was not relaxed.**

`infrastructure` is the stage that can carry a template change, and it requires
`PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE` naming the instance — confirming the host **may be
destroyed**, which would have lost the deployed case, the Telegram binding and the certificate.
It was **not** used.

What carried the release instead was a parameter-only change set against the **previously
deployed template**, authorised explicitly by the project owner and gated on an empty resource
change list before execution:

```text
create-change-set --use-previous-template  ImageTag=4cfb74de7cc2, all others UsePreviousValue
Status CREATE_COMPLETE   ExecutionStatus AVAILABLE   ChangeCount 0   Changes []
```

`ImageTag` appears **nowhere in any resource** in the deployed template — the template's own
comment says so: *"a stack update carrying a new `ImageTag` reports `UPDATE_COMPLETE`, leaves the
instance id unchanged, and the host goes on serving the image it first booted with."* There are
zero `${ImageTag}` substitutions in it. So the empty change list is a property of the template,
not a coincidence. The parameter diff was `ImageTag` alone; `HostAmiId` and
`SeedDemoFixtureOnFirstBoot` were carried forward unchanged.

**This is recorded as a gap rather than a pattern.** The deployed stack still cannot receive the
current template through any non-destructive route, and §10.1's conclusion stands: that gap is
closed only by replacing the host, which nothing here authorised.

### 6.2 What the release proves

| claim | evidence |
|---|---|
| the deployed SHA is the hardening commit | `/healthz` `image` **`4cfb74de7cc2`**; smoke's `deployed-image` agrees |
| the API and worker are healthy | five containers up, `RestartCount` **0** on `api`, `worker`, `caddy`, `mcp` |
| the provider is still Telegram | `pp channel check` **inside `worker`**: `channel: telegram`, `provider: telegram` |
| links are still configured | a forged approval `GET` is **`404 LINK_NOT_FOUND`**, not `503` |
| the host was rebooted, not replaced | instance `i-087c742587f83d61d`, AMI `ami-0fa4996c14e7d501e`, launch `2026-09-18T10:19:33Z` — **all unchanged**; `boot_id` `b0124ede…` → `ba8c17a0…` |
| no AMI moved and nothing reseeded | `DeclaredHostAmiId` `ami-0fa4996c14e7d501e`, `DemoFixtureSeededOnFirstBoot` **`false`** |
| the database is untouched | RDS `db-U2JWQBTINX6W6GAB56EOTHOCSM`, created `2026-09-11`, `available`, private, encrypted |
| smoke | **12/12 passed, 0 failed, 0 skipped** |

**The reconciled `converge.sh` did its job, and that is the convergence proof:**

```text
converge.sh   09105b1001184df4b26a2fc8a06581c62c38f20c6a72389d911a5e5258eefe9c  root root 750
boot                       2026-09-22 19:44:22
env/channel.env mtime      2026-09-22 19:44:36      <- fourteen seconds after the boot
env/channel.env sha256     c3a6e4dea3f37c58707db90c2690fb1ab3ee2f51b6d123ad47b4307922225240
```

The file was **regenerated from SSM by the instance role at boot**, and its hash is identical to
the hand-written one it replaced. `env/channel.env` is now derived. A rotated bot token would be
picked up at the next boot, which was the whole point of section 8.7's complaint.

### 6.3 The deployment created nothing

Every count identical before and after. Both ledgers did not even grow.

| | before | after |
|---|---|---|
| `cases` / `case_states` | 1 / `RESOLVED` | **identical** |
| `customers` / bound | 6 / 1 | **identical** |
| `approval_requests` / `approval_decisions` / `plan_approvals` | 1 / 1 / 1 | **identical** |
| `inbound_replies` | 1 | **identical** |
| `outbox` | 3 rows, `MESSAGE_SEND` ×1 `DELIVERED` attempts 1 | **identical** |
| `audit_events` / `domain_events` | 218 / 277 | **218 / 277** |
| tracks | `pr-a` `RECOVERED`, `pr-b` `RECOVERED`, `pr-c` `ESCALATED`, `pr-d` `ESCALATED`, `pr-e` `UNAFFECTED`, `pr-f` `UNAFFECTED` | **identical** |
| orders | `EXT-A v2 AMENDED`, `EXT-B v2 AMENDED`, `EXT-C…F v1 ACCEPTED` | **identical** |

`sendMessage` calls made by this release: **0**. `getUpdates` calls: **0**, as ever.

### 6.4 The fixes, proved on the deployed build

The deployed `worker`, asked directly:

```text
CONSENT           : Open the secure link below to approve or decline this change. If you
                    decline, the bakery will follow up.
CONFIRMATION      : To approve or decline this change, use the secure link in our earlier message.
says_reply        : False
telegram ref ->   telegram:***
engine chan  ->   tg:***
order ref    ->   amd-e735e9398046
```

And `pp case-status` against the real case `a3810ae5-…`, which is the surface section 11.7 said
discloses a real person's identifier:

```text
approval e9832010-… (OPT-4D3FFD) ANSWERED, deadline 2026-09-22T21:47:06…
  sent 2026-09-22T16:57:41… ref telegram:***, replies 1
   8. pass  sender is the order's approval channel
      expected tg:***
      actual   tg:***
effect MESSAGE_SEND DELIVERED (attempt 1, ref telegram:***)
effect ORDER_AMEND  DELIVERED (attempt 1, ref amd-40e195e65abe)
```

Counted on the unmasked text inside the host: **two** masked references, **two** masked channels,
and **zero** occurrences of `telegram:<digits>` or `tg:<digits>` anywhere in the output. The
order-system references are untouched, because they name nobody. In the worker's log for this
boot: `chat_id` **0**, `sendMessage` **0**, `getUpdates` **0**.

## 7. What was not done, stated plainly

- **No refusal path was exercised live**, and none was manufactured. `STALE`, `EXPIRED`,
  `UNAUTHORIZED` and `NOOP` remain proved only by their tests. Inventing drift to watch a refusal
  would be staging rather than measuring.
- **No second proposal, no second message, no new binding, no reseed.** `sendMessage` has still
  been called exactly once in this deployment's history, and that call was section 10's.
- **Telegram inbound is still unbuilt**, deliberately, and this change makes it less likely to be
  wanted rather than more.
- **CloudWatch still holds the old log lines.** Redacting the emitter does not rewrite history,
  and the entries written before this release still carry the identifier. Frozen evidence is not
  silently rewritten; this is recorded instead.
- **The deployed stack's template is still behind `HEAD`.** §10.1's gap is unchanged: it can be
  closed only by replacing the host. The *host* is reconciled; the *template the stack records*
  is not.
- **`deploy.sh` still has no stage that moves `ImageTag` alone.** The release above used a
  hand-built change set under explicit authorisation, gated on an empty resource change list.
  That is a documented one-off, not a new release path.
- **CI has not run on this commit.** Local validation is green — `ruff check`, `ruff format`,
  `mypy` across 288 source files, all 30 import-linter contracts kept, and the focused suites
  below — but GitHub CI remains the broad regression authority and has not yet seen it.
- **`G8` remains the open gate.** Nothing here touches the effect-set headline (`11/16`,
  immutable), the sealed holdouts, or any `SUR-1` artefact. This work is hygiene on the G6 loop
  that was already closed, not progress through G8.

## 8. What this closes

The first real customer loop, recorded in sections 10 and 11 of
[`deployed-customer-channel.md`](deployed-customer-channel.md), ran end to end against a
message that told the customer to do something impossible and a system that read a real person's
Telegram identifier out on five surfaces, two of them public. Both are closed, in the deployed
build, with the loop's own evidence intact and nothing in the world moved to prove it.

# Redeploying HEAD to the live host

Date: 2026-09-16
Status: **done.** `https://184.194.40.87.sslip.io` serves `b62779d6e975`. No AWS resource was
created, deleted or resized, no IAM was changed, the database was not reseeded or truncated, and
no product code was changed to make the deploy succeed.

Deployed under
`arn:aws:sts::<ACCOUNT_ID>:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`
in `us-east-1`, stack `promisepatch-prod`, instance `i-087c742587f83d61d`.

## 1. What the host served before

| | before | after |
|---|---|---|
| `/healthz` `image` | `acfdd975dd4d` | `b62779d6e975` |
| stack `ImageTag` | `acfdd975dd4d` | `b62779d6e975` |
| SSM `image-tag` | `acfdd975dd4d` | `b62779d6e975` |
| schema revision | `0008_observer_worker_role` | `0008_observer_worker_role` |
| MCP tools served | **four** -- `report`, `clarify`, `confirm`, `status` | **five** -- plus `withdraw` |
| instance id | `i-087c742587f83d61d` | `i-087c742587f83d61d` (not replaced) |

`acfdd975dd4d` is 87 commits behind HEAD. The three image declarations already agreed before this
session began: the drift `docs/deployment-declaration-drift.md` records was closed before it, so
correcting `ImageTag` here was an ordinary release write rather than a repair.

## 2. Migrations

**None.** `git diff --name-status acfdd975dd4d..HEAD -- apps/backend/alembic` is empty across all
87 commits; the head revision is `0008_observer_worker_role` at both ends. `/readyz` reported
`migrations.at_head: true` before and after. Nothing needed a manual or destructive step, and the
`migrate` container's ordinary `alembic upgrade head` was a no-op.

## 3. `PP_DEMO_SESSION_ENABLED`, and why SSM cannot answer for it

**It is not in SSM, and it cannot be.** The setting is written into
`/opt/promisepatch/env/api.env` by the CloudFormation template's `UserData`, which cloud-init runs
**once per instance**. The three parameters `converge.sh` re-reads at every boot -- `compose`,
`caddyfile`, `image-tag` -- do not carry it, and `converge.sh` rewrites no `env/*.env` file. A
`get-parameters-by-path` over `/promisepatch/prod` returns eleven parameters and none of them is
this one.

So the question was answered by exercising the deployed surface instead:
`POST /api/auth/demo-session` returns `200` with the observer worker. That endpoint does not exist
when the setting is false, so it is on -- and because `worker` and `api` share `env/api.env`, the
same read settles it for the boot provisioning that is gated on it. It needed no configuration
change, which is what `docs/seeded-demo-case.md` predicted, now checked against the deployment
rather than against the working tree.

Two consequences worth stating. First, the template's own comment on that line -- *"Setting it
back to false removes the endpoint at the next boot with no code change"* -- contradicts the
comment forty lines above it, which says the provisioning script runs once on an instance's first
boot and not again. Turning this setting off is therefore not a release; on the evidence of how
`converge.sh` is written it would need an instance replacement. That was not tested here. Second,
a setting invisible to SSM is invisible to anyone auditing the deployment without shell access on
the host.

## 4. The AMI the deploy would have replaced the host over

**`./deploy/deploy.sh stack` could not be run as written, and it is the one deviation in this
release.**

`host_ami_id()` resolves the newest Amazon Linux 2023 arm64 image at every run, deliberately, so
that no AMI id is pinned in git. The stack was created against `ami-0fa4996c14e7d501e`; Amazon has
since published `ami-07b9559027f889918`. `ImageId` on `AWS::EC2::Instance` is a replacement
property, so the stage would have passed a changed AMI into a resource that cannot absorb one.

This was proved rather than argued. A change set built with the newly-resolved AMI, created and
never executed, reported:

```
Modify  AWS::EC2::Instance        Host                    Replacement: True
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation    Replacement: True
```

A replacement would have created a new EC2 instance, re-run cloud-init -- which ends in
`compose run seed`, erasing every case on the host -- and re-ordered the Let's Encrypt
certificate. Three of the five weekly duplicates for this name had already been issued.

The change set was deleted unexecuted. The stack was then converged with `HostAmiId` pinned to the
value it already carried, through the same `aws cloudformation deploy` call `stage_stack` makes,
with the same deployment role and the same other parameters. Its change set reported **zero
resource changes**; the update completed leaving the instance id unchanged.

`deploy.sh` is left unfixed. The fix is a decision about intent -- whether a release should pick
up a host AMI at all, and if so how a host is rebuilt without losing its cases -- and this was a
deployment session.

## 5. What verification actually showed

**`/healthz` names HEAD, and the schema is at head.** `image: b62779d6e975`,
`boot_id: 19f16561-...`; `/readyz` reported `expected_revision` and `actual_revision` both
`0008_observer_worker_role`, and the runtime connection authenticated as `promisepatch_app` rather
than as the migration user.

**The MCP surface serves five tools.** `tools/list` over the public endpoint returned `report`,
`clarify`, `confirm`, `withdraw`, `status`, and `initialize` negotiated protocol revision
`2025-11-25`. The same call before the deploy returned four; the README's claim of five was true
of the repository and false of the deployment, and is now true of both.

**The judge entry lands on a real open case.** `POST /api/auth/demo-session` issues the observer
session, `GET /api/cases` returns four cases, and the `PLANNED` one renders populated bands --
three authority groups, a `next_action` owned by `YOU`, per-promise reasons, and a causal chain
with four steps and `path_count: 1`.

It lands there **because the cases from 2026-09-13 survived, not because this deploy provisioned
one.** The deployed worker's new provisioning ran and declined, as designed:

```
{"event": "worker.demo_case", "action": "PRESENT",
 "detail": "a case already exists; nothing was touched"}
```

logged at both worker starts in this session. That is the additive-only guard proved on the live
deployment -- exactly the behaviour that refuses to repeat P6.2's re-seeding defect -- but it
means the `OPENED` branch, the one that creates the canonical case on an empty deployment, was
**not** exercised here and is still proved only by its tests.

**Every deployment smoke check passes: 12/12, five of them refusals** -- unauthenticated
`POST /mcp` is `401`, an unlisted `Origin` is `403`, an unlisted `Host` is `421`, an unsigned
order-system event is refused, and `POST /internal/intents/report` from outside is `404`. Run
twice: once after the rollout and again after the restart.

**The canonical conversation runs end to end over the public transport.** Six turns from outside
AWS against `https://184.194.40.87.sslip.io/mcp`, every verb correct on one attempt each --
`REPORT`, `STATUS`, `CLARIFY`, `STATUS`, `CONFIRM`, `STATUS` -- with a real Bedrock Nova call per
turn (`semantic.answered`, `us.amazon.nova-2-lite-v1:0`, 1,823-1,847 input tokens a turn). The
confirmation reported permission and not completion: *"Nothing has been changed yet - ask me for
the status to hear what actually happened."*

**It did not reach the outcomes P6.2 recorded, and that is section 6.**

**A restart neither duplicated the seeded case nor erased it.** `ec2:RebootInstances` on
`i-087c742587f83d61d`; `boot_id` moved `19f16561-...` to `1abf8699-...`, so the process really
restarted. The case list before and after is byte-identical -- the same four ids, states and
`opened_at` values in the same order -- the fixture's `anchor_at` and `loaded_at` are unchanged at
`2026-09-13T18:35:32`, the image is still `b62779d6e975` and the surface still serves five tools.

## 6. What deployment found that reading could not

**The demo narrative decays with wall-clock time since the fixture was seeded.** The canonical
conversation's own outcome has changed, on the same fixture rows, since 2026-09-13:

| | 2026-09-13 (`744f5f78`) | 2026-09-16 (`7e6319bc`) |
|---|---|---|
| `EXT-A` Priya Nair | `AUTO_RECOVERABLE` / `PREAPPROVAL_COVERS` -> **`RECOVERED`** | `NOT_REACHABLE` -> **`UNTOUCHED`** |
| `EXT-B` Tomas Lindqvist | `APPROVAL_REQUIRED` -> `ESCALATED` | unchanged |
| `EXT-C`, `EXT-D` | `BLOCKED` -> `ESCALATED` | unchanged |
| promises left alone | **2** | **3** |

The pure engine is **byte-identical** between `acfdd975dd4d` and HEAD -- `git diff` over
`packages/promise-graph/src` across all 87 commits is empty -- so the classification code did not
move. What moved is the clock. Every fixture instant is an offset from the anchor the seed
recorded, and that anchor is `2026-09-13T18:35:32`: `EXT-A`'s production task runs anchor+300 to
anchor+420 minutes, which closed two days before this conversation was held. `EXT-B`'s approval
deadline is now read out to a worker as `2026-09-13 23:35 (UTC)` -- a time in the past -- and the
confirmed case settles to `SETTLED` in one turn instead of waiting on a customer.

None of this is a correctness defect: the engine is right that an exception reported today cannot
reach a task that finished on Monday, and the product says so in its own words rather than
pretending. But **the band the demo exists to show -- one promise recovered without asking anybody
-- is gone from the deployed host**, and the only thing that restores it is re-seeding, which
erases every case and which this session was correctly forbidden from doing. A deployment
demonstrated days after it is seeded is not demonstrating the scenario its own documents describe.

**`PP_DEMO_SESSION_ENABLED` is unreadable from the control plane.** Section 3. The pre-deploy
question as posed -- read it from SSM -- has no answer there, and the template contradicts itself
about whether the setting can be changed without replacing the instance.

**The smoke suite turns a missing operator credential into what looks like a lost refusal.**
Without `PP_MCP_BEARER_TOKEN` in the shell, `check_origin_refused` sends no `Authorization`
header, the bearer check fires in front of the Origin check, and the run reports

```
FAILED   origin-refused   an unlisted Origin is 403  (status 401, expected 403)
```

which reads exactly like a deployment that has lost its Origin allowlist. `check_protocol_revision`
handles the same absence honestly, by skipping and saying why. The first run of the suite in this
session was 10/12 for that reason alone; with the token set it is 12/12 and the Origin refusal is
a real `403`. The check is not wrong about the deployment -- it is wrong about the operator, and
it does not say so.

## 7. Still open

- **`deploy.sh stack` still replaces the host whenever Amazon publishes a newer AL2023 arm64
  AMI.** Worked around here by pinning; unfixed in the script, and it will recur on the next
  release.
- **The seeded case's `OPENED` branch is unproved on a deployment.** It can only be exercised on a
  host with no cases at all, which this one is not.
- **The deployed demo narrative is degraded** and cannot be restored without a reseed that would
  erase four cases, including the `PLANNED` one a judge currently lands on.
- **Telegram is untouched** and the customer channel remains unbuilt, as `docs/g7-closeout.md`
  records.
- `REMAINING_WORK_ASSESSMENT.md` is untracked in the working tree and was not committed.

## 8. What was not touched

No resource was created, deleted or resized: the stack update reported zero resource changes and
the instance id is unchanged. No IAM policy, role or trust relationship was modified. The database
was not reseeded, truncated or migrated -- the fixture's `loaded_at` is still the one from
2026-09-13. Two change sets were created; one was executed and one was deleted unexecuted. No
secret was printed, committed or rotated. TLS verification was left on everywhere.

# Post intake release revalidation 2026 09 30

The post-ADR-0027 release is deployed and its reopened validation obligations are complete. Product release: `283f63f2845f8c5e93b2a791eebc15bc4de3f4d7`; image: `283f63f2845f`. This additive closeout leaves historical evidence unchanged, including the original v1 **11/16** headline and prior v2 result. No product code, manifests, labels, IAM or infrastructure design was changed.

## Repository and authority

Starting local main was `7ff5cf49245d9eac43222737219c8383307766ea`. Fetch verified the exact expected origin/main; a normal fast-forward established the release SHA above. Tracked source was clean throughout release. Eleven pre-existing untracked historical artifacts were left untouched.

AWS identity was verified before work and during final reconciliation: account `265243686715`, role `PromisePatchDeveloperRole`, ARN `arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`.

Exact-SHA [pr workflow 36759222324](https://github.com/Asembris/PromisePatch/actions/runs/36759222324) passed all 13 jobs: backend/postgres, coverage, browser, semantic boundary/evaluation, MCP, frontend, mypy, ruff, import-linter, hypothesis, order contract/system and gitleaks. The historical v1 workflow remained red and was not altered.

Historical release remains repository `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, deployed image `4529a802e34e`. It is distinct from this release.

Authority: CLAUDE.md, ADR-0027, G8 closeout/preparation and original R1–R5, non-destructive-release, demo-world-restore, effect-set release condition/run protocol, demo-contract runbook/runner, deployment implementation/tests. No holdouts were opened. The required new v2 run was permitted without a material protocol conflict.

## Release path and reconciliation

The ordinary template proposal reproduced the documented template gap: conditional replacement of Host through UserData and ElasticIpAssociation. It was **not executed**, and was deleted. The existing previous-template parameter-only procedure in `non-destructive-release.md` was used.

Executed change set: `post-intake-283f63f2845f/fb349645-4323-4d60-be95-c203109b058f`, CREATE_COMPLETE/AVAILABLE, resource changes `[]`. Only ImageTag moved `4529a802e34e` → `283f63f2845f`. All 12 inherited infrastructure parameters matched live values, seed flag false. No replacement, removal, ingress/networking/AMI change or unrelated parameter movement. Exact SHA, current/intended tag, parameter movement, empty changes and host identity were printed before execution.

Both immutable ECR tags were absent before build. Repository `deploy.sh images` successfully built/pushed only the required ARM64 images:

| Image | Digest |
| --- | --- |
| backend | `sha256:ef141b461ca6a1ad11ed6da2fc06cccd65141d4df38554f61143c64aac030f19` |
| order-simulator | `sha256:5ee545b9dec1ef69f6c11feb6ef688d3631da69f62b5bb2be9dc2520fd90201a` |

Compose/Caddy configuration content stayed identical after accounting for shell trailing CRLF; SSM versions advanced to 15/14, image tag 9 → 10. Stack update timestamp: 19:39:56.613Z; completion: 19:40:02.408Z. Only stack events occurred. `deploy.sh rollout` restarted the existing host. Executed change set was deleted, leaving zero change sets.

| State | Before | After |
| --- | --- | --- |
| Stack | UPDATE_COMPLETE | UPDATE_COMPLETE |
| ImageTag / DeclaredImageTag / SSM tag | `4529a802e34e` | `283f63f2845f` |
| EC2 | `i-087c742587f83d61d` | unchanged |
| Launch time | 2026-09-18T10:19:33Z | unchanged |
| AMI | `ami-0fa4996c14e7d501e` | unchanged |
| Public address | `184.194.40.87` | unchanged |
| RDS | `promisepatch-prod` / `db-U2JWQBTINX6W6GAB56EOTHOCSM` | unchanged |
| RDS engine/status | PostgreSQL 16.13 / available | unchanged, no pending modifications |
| API boot | `3e90146d-1484-40e9-8ab8-02cda046a664` | `69adea88-3869-491e-8633-3ec42ae8c6ec` |
| OS boot | `109dccdf-b7fb-4882-8b28-c963b2f0f7b9` | `017b05ec-fa6d-420f-a730-c282d4441f1e` |
| Migration | `0009_human_plan_approval` | `0010_condition_clarification` |
| Immediate-release fixture anchor/loaded-at | 2026-09-24T20:54:53.431361Z | unchanged |
| Immediate-release fixture digest | `850c7ceafa068a9f5dc8da5f0fcb4d7f13e4f77937b61b4e626e78c8bbcbebe4` | unchanged |

All CloudFormation physical resource IDs remained unchanged, including EIP association, database, security groups/rules, profile/role/log group. Converge script hash and Caddy/order-simulator volumes stayed unchanged. Immediate pre/post fixture and ledger reconciliation proved **no automatic reseed or restore during deployment**. Migration 0010 safely changed the allowed clarification slot constraint, exit 0.

## Deployment checks

Live health reports the new image; readiness is ready, database reachable, role `promisepatch_app`, head `0010_condition_clarification`. API, worker, MCP, root/frontend and simulator are healthy. MCP initialization passed protocol 2025-11-25; root/deep links worked, internal HTTP access was refused and unsigned webhook returned 401. Simulator health/readiness passed with seeded state retained.

Committed smoke reported **9/12** from the workstation. Three refusal probes timed out through the documented local TLS interceptor. Independent host-local Caddy probes returned the required missing-bearer 401, forbidden-Origin 403 and forbidden-Host 421. This is not a 12/12 workstation smoke claim. Public CA-bundle procedure was used without disabling TLS. Bearer retrieval stayed in memory; no secrets/destinations were printed. Informational Bedrock GetFoundationModel was denied, with all nine required preflight checks passing; IAM was not broadened.

Final control-plane/CI/host records are preserved below. Final live fixture is hollow-oak, anchor/loaded-at `2026-09-30T20:54:00.016517Z`, digest `033f5032c0e6a2a1f05625b6e3c64ddb7d82bc662f97c64a91b916b035db6d68`; one settled case, three outbox effects, zero unsettled effects. Infrastructure identities stayed unchanged through rehearsals.

## Physical intake proof

Proof used local disposable PostgreSQL, exact release source/head 0010, and the existing scripted semantic provider. It is **not live Bedrock proof**. This command passed all tests:

```text
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_exception_intake.py apps/backend/tests/test_semantic_intake.py apps/backend/tests/test_physical_interpretation.py apps/backend/tests/test_migration_history.py -q
```

Required negatives were tested: heavy cream not spoiled; cream fine/do not mark spoiled; oven broke last year/works today; asking whether cream spoiled; conditional spoiled cream; invoice request with schema-valid STOCK_UNUSABLE proposal; oven manual request with schema-valid EQUIPMENT_UNAVAILABLE proposal. No unauthorized physical fact, loss, outage or recovery was permitted. Negation/question/conditional/past assertions were refused; the invoice proposal required CONDITION, worker no wrote no fact; manual proposal failed grounding.

Positive missing raspberry delivery, spoiled cream and broken oven controls passed. Legitimate model-assisted cream wording produced a closed CONDITION question, no physical write before answer, worker yes permitting deterministic worker-attested writeoff, worker no writing no physical fact. No paid call. Test output is preserved in the session transcript, not an invented raw file.

## New deployed R1 through R5

Original frozen reader was used unchanged, SHA-256 `c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`. Supplemental full-table hashes were read-only. Original partition/timing semantics were preserved, including preparation section 10.2 for R3. Real Maya BROWSER_SESSION confirmation used ADR-0018/current demo-contract human authority; this differs from historical OPERATOR_CONSOLE captures and is recorded explicitly.

Every successful run: six promises → four threatened/two untouched → one auto recovery, one customer-decision track, two escalation tracks. Final: two RECOVERED, zero WAITING, two ESCALATED, two UNAFFECTED; case RESOLVED. Each had one plan approval/request/decision/reply, two ORDER_AMEND and one MESSAGE_SEND, distinct keys, delivered attempt 1. Two task holds; untouched task E STARTED/unheld. EXT-A/B v2 authored almond-4/rose-3 matched store; C..F stayed v1. Untouched/unrelated hashes stayed identical; attribution counts zero. Each recorded ten passed post-answer checks.

All following times UTC, 2026-09-30:

| Run | Case | Plan approval | Worker stop → start | Phone action / decision | Invariant |
| --- | --- | --- | --- | --- | --- |
| R1 attempt 2 | `1c10eb3b-27fd-57a7-9462-c98a323f6de8` | 20:16:35.308725 | 20:19:15.462350 → 20:19:18.426022 | 20:22:10.747988 | PASS: waiting restart stable immediately and >90s, recovery after answer |
| R2 | `7db26377-c80a-57cc-9366-3d1ff26715c8` | 20:32:40.799188 | 20:30:51.470659 → issued 20:35:23 | 20:36:20.215683 | PASS: stopped pending steps attempt 0/no lease, no effects; new worker dispatches |
| R3 | `9f9135c7-ea0e-57ff-856c-66cf110894e5` | 20:40:32.704855 | 20:41:19.283777 → issued 20:45:23 | inbox 20:42:08.436299; decision 20:45:28.309705 | PASS: offline inbox, no decision/revalidation/recovery until start |
| R4 | `bc34373a-87a6-5f5d-b89b-a0135eab99a7` | 20:48:43.836620 | 20:51:01.186731 → 20:51:04.155817 | 20:49:36.217496 | PASS: settled restart has no changes through >90s |
| R5 | `d1457010-1a92-5a20-92ca-989dd1a1e744` | 20:54:27.378592 | 20:55:26.804128 → 20:55:29.804655 | 20:57:58.130723 | PASS: waiting restart repeated, answer then new-worker recovery |

Detailed counts/hashes/attempts/worker identities are in unmodified `r*-pass.txt` and raw logs. The user reported exactly one new Telegram message per run; token/link/destination scans were zero. No provider-level exactly-once guarantee is claimed. R1/R2 FINALIZE_RECOVERY retries waited for mirror echo as historically documented, without repeating external effects. Compose start in R2/R3 reran migrate successfully, without seed/infrastructure change.

### Every intentional restore

All seven restores followed successful `pp restore-demo-world --dry-run` and all settings/preconditions, then `--confirm destroy-and-restore`. Canonical live Telegram binding was preserved/reverified without printing it. No manual truncation, down -v, TLS deletion or bypass occurred.

| Environment/run | Anchor and loaded-at UTC | Digest |
| --- | --- | --- |
| Live R1 attempt 1 VOID | 20:01:46.428359Z | `a65bc8722f243f7997107fbcf0f3df40141a1c27f03aa299abff4e2295f35417` |
| Live R1 attempt 2 | 20:15:25.238842Z | `60e69ef8d3d419ad6b3c84463fa9f6af104d810c066a330da35c6535e8eab98a` |
| Live R2 | 20:30:47.437928Z | `261431946aa2a71b5288078a3a4c648e738c2282a762f0ad09047ad3d5e2710b` |
| Live R3 | 20:39:10.086651Z | `2a9d41f8e4aa8313f8dcf5e733649350de5d0c05a4d0bbfbacfaff6521f9a8f3` |
| Live R4 | 20:48:00.894045Z | `4929fc5202040fe798b6d9eaa85ff146eac5f4ee690352941777ee2e39ec02d7` |
| Live R5 | 20:54:00.016517Z | `033f5032c0e6a2a1f05625b6e3c64ddb7d82bc662f97c64a91b916b035db6d68` |
| Local demo | 21:07:06.743409Z | `1095d7a991e888ff63f280de6205ac2d8382fe4708312e981b83e503ea63198f` |

R1 attempt 1 case `46ee1ee8-259a-5e47-b4fe-fbba82604915` expired at 20:11:49 before human confirmation/restart. Zero approvals/outbox effects. Preserved **VOID** under preparation section 3.1; no silent failed-run retry. Void/expiry files retained; initial restore output exists only in session transcript.

## V2 release condition

Published v2 manifest unchanged: SHA-256 `77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd`, version 2.0.0. Approved runner 1.1.0. Identity/coverage preflight passed. Predeclared required scored run taken **once**, result **16/16**, S01–S16 PASS, exit 0; 19:44:49.748709Z–19:47:14.050625Z.

- [Raw capture](effect-sets/runs-v2/20260930T194449748709+0000-scored.json), SHA-256 `385aec75f559bd0c3407c509e1993babc765203605b91e29d1795fc8f8425b51`.
- [Raw console log](effect-sets/runs-v2/20260930T194449748709+0000-scored.log), SHA-256 `03af55231e718e21e43870baf953afdd05a5c3e6f99845cbc927ba689ad1bce9`.

Implementation SHA matches exact release. Capture records `working_tree_dirty=true` because eleven historical untracked artifacts remained, while tracked product source was clean. A separate clean worktree was preferred but not used. Raw field unchanged; no rerun. Historical v1 11/16 and prior v2 remain historical.

## Demo contract

The committed **local** procedure ran against exact-release local images/head 0010, fake semantic/customer channel per runbook. It is not a live AWS runner or live Bedrock observation; live rehearsals separately proved the deployed funnel. Unchanged `scripts/demo_contract.py` SHA-256: `4845ea25fed47fe3372d7cd9ebddc5f764df0d1f216b85fee80796e575b5c21d`.

The user personally confirmed local case `1149d61f-4a3b-5467-b86e-ad019ec00e6d` once using pp confirm-plan as Maya, OPERATOR_CONSOLE at 21:08:51.145615Z. Runner continued only after verification. An actual local worker restart occurred at its checkpoint. The runner's fake customer transport is not represented as real phone interaction.

**DEMO CONTRACT PASS (47 assertions), exit 0.** Console confirmation skips two browser-intent assertions in the unchanged runner; the browser path's 49 headline is not claimed. Storyboard/assertions unchanged. Six/four/two funnel and eventual two recovered/zero waiting/two escalated/two untouched passed. Raw build/dry-run/restore/runner logs preserved. Temporary local services stopped afterward; volumes retained.

## Limitations and operator anomalies

- Workstation smoke 9/12, with independent host-local proof of the three refusal checks.
- Physical test stdout and some initial release/proposal/preflight output live in the session transcript; no missing raw capture is invented.
- Read-only queries initially referenced nonexistent columns. Errors preserved, corrected reads passed. No product defect.
- Automatic review rejected an equality projection as possible private-identity disclosure before execution; replaced by aggregate identity-match count, without disclosure/bypass.
- R1 broad numeric CloudWatch scan matched timestamps/durations/header metadata; initial capture retained, separate destination fingerprint check zero.
- Local demo's inherited Bedrock settings triggered a pre-write guard; temporary process environment selected runbook fake providers without code/assertion changes or paid call.
- Existing npm warnings: two moderate and one high vulnerability, not repaired in this scoped session.
- Sandbox launcher failures required reviewed escalated execution. SSM compose-exec stdin handling corrected before restore; explicit dry-run success rechecked.
- Human actions: five real browser plan approvals, five phone APPROVE actions, per-run message-count confirmations, and one real local console plan confirmation. No fabricated live consent.

## Additive evidence and freeze

New raw captures: [post-intake-20260930-283f63f2845f](rehearsals/runs/post-intake-20260930-283f63f2845f/). Copied files are byte-identical to session captures; `capture-integrity.json` records hashes. Narrow new-file Git attributes prevent line-ending normalization. Raw captures retain original CRLF/trailing blank lines: full diff whitespace checks flag them, while authored documentation formatting/whitespace checks pass. V2 raw bytes remain in runs-v2. This new closeout leaves all old R1–R5, benchmark/run captures, deployment evidence and Phase 7/G8 claims untouched.

Evidence branch `docs/post-intake-release` was created from exact release SHA only after all validations. Documentation/captures only; no PR/merge/main push. Commit identity and final Git status are reported externally to avoid a self-referential commit field. Historical untracked artifacts remain untracked.

All reopened ADR-0027 obligations are complete within the explicit scopes/caveats above. Product release can be frozen again at `283f63f2845f8c5e93b2a791eebc15bc4de3f4d7`.

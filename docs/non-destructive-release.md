# A release is not allowed to destroy the deployment

Date: 2026-09-17
Status: **closed locally. Nothing has been verified against AWS**, and section 7 says exactly
what a live check would have to show. No AWS resource was read, created, updated or deleted
while this was written.

> **Superseded on 2026-09-18 by [section 9](#9-the-live-check-performed).** The status line
> above is left as written. The live check has since been run against `promisepatch-prod`, it
> found a defect in the guard described in section 4 item 3, and section 9 records both what it
> proved and what it left unperformed.
>
> **Extended on 2026-09-18 by [section 10](#10-the-template-needs-a-way-in-and-it-is-not-a-release).**
> The guard section 9 fixed also means this repository's template can no longer reach the
> deployed stack through a release at all. Section 10 adds the one operation that can carry it,
> and the confirmation it will not execute without. Nothing in section 10 was run against AWS.
>
> **Performed on 2026-09-18, recorded in [section 11](#11-the-migration-performed).** Section
> 10.7's procedure has been run against `promisepatch-prod`. The stack is now on this template,
> the host was **not** replaced, every case survived, and an ordinary release against the live
> stack now proposes no resource change at all. Section 11.8 says what it still leaves unproved.

This closes the first item of [head-redeploy-2026-09-16.md](head-redeploy-2026-09-16.md)
section 7: *"`deploy.sh stack` still replaces the host whenever Amazon publishes a newer AL2023
arm64 AMI. Worked around here by pinning; unfixed in the script, and it will recur on the next
release."*

## 1. The hazard, traced end to end

An ordinary application release is `./deploy/deploy.sh all`, which runs `stack`. Before this
change, `stage_stack` did:

```bash
ami="$(host_ami_id)"          # the *newest* AL2023 arm64 image, resolved at every run
...
  "HostAmiId=${ami}"
```

and the template does `ImageId: !Ref HostAmiId` on an `AWS::EC2::Instance`. `ImageId` is a
replacement property. So the chain was:

| step | what happened |
|---|---|
| 1 | a release runs `stack` |
| 2 | Amazon has published a newer AL2023 arm64 image since the stack was created |
| 3 | `HostAmiId` changes, so CloudFormation **replaces the instance** |
| 4 | the new instance runs `UserData`, which cloud-init runs once per instance |
| 5 | `UserData` ends in `docker compose run --rm -T seed` |
| 6 | `seed` runs `pp reset-demo-state` against **RDS, which outlives the host** |
| 7 | every case, every step-ledger row and every consent record is replaced by the fixture |

The whole of it reports `UPDATE_COMPLETE`.

**This is not a prediction.** On 2026-09-16 a change set built exactly this way was created and
read rather than executed:

```
Modify  AWS::EC2::Instance        Host                    Replacement: True
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation    Replacement: True
```

It was deleted unexecuted, and that is the only reason the four cases on the deployed host still
exist. The protection was a person thinking to look.

## 2. What was already right, and was not duplicated

The audit found four protections already in place. None of them was touched.

- **`converge.sh` does not seed.** The systemd unit runs it at every boot; it re-reads the
  composition, the Caddyfile and the image tag from SSM and pulls. A *reboot* has never been
  able to reseed, and `test_a_restart_cannot_reseed_the_database` holds that.
- **The `seed` service is profiled** and nothing `depends_on` it, so `compose up -d` cannot
  reach it.
- **RDS carries `DeletionPolicy: Snapshot` and `UpdateReplacePolicy: Snapshot`.** The first was
  asserted; the second was not, and now is, added to the existing durability test — it is the
  half a release could actually have reached.
- **The three image declarations are compared before a rollout.** `require_image_declarations_agree`
  is unchanged.

The gap was never the reboot path. It was the `stack` stage, and no test looked at it: the
existing `test_a_release_is_a_parameter_write_and_a_reboot_rather_than_a_new_instance` inspects
`stage_rollout` only.

## 3. The release model, before and after

| | before | after |
|---|---|---|
| host AMI on a release | newest available, resolved every run | the value the stack already declares |
| who may resolve a newer AMI | every release | a first create, and `host-image` |
| demo seed on a release | whatever the last deploy left | the literal `false`, unreachable from the environment |
| plan visible before mutation | no — `deploy` executed its own change set | yes — the change set is built, described, and only then executed |
| a release that would replace a resource | executed | refused, change set deleted, nothing mutated |
| replacing the host | a side effect | `./deploy/deploy.sh host-image`, confirmed by instance id |
| reseeding | a side effect of replacement | only `PP_DEPLOY_SEED_ON_FIRST_BOOT=true` with `host-image` |

The three operations are now separate by construction rather than by care:

- **Application release** — `images`, `config`, `stack`, `rollout`, `smoke`. Moves the image tag.
  Cannot name an AMI, cannot arm the seed, cannot execute a change set that replaces anything.
- **Infrastructure / AMI upgrade** — `host-image`. Prints the AMI it moves to, the instance it
  destroys, the certificate re-order and whether the database will be erased; then refuses
  unless `PP_DEPLOY_REPLACE_HOST` names the exact instance being destroyed.
- **Fixture reset** — `PP_DEPLOY_SEED_ON_FIRST_BOOT=true` on a `host-image` run, and nothing
  else. See section 6 for the limit this carries.

## 4. The safeguards, and where each one lives

1. **`release_host_ami_id`** reads `HostAmiId` back off the stack. `stage_stack` calls it and
   does not mention `latest_host_ami_id` at all, so a release cannot resolve a newer image. A
   stack that does not exist yet has nothing to preserve and no cases to lose, so a first create
   resolves the newest image — the only implicit resolution left in the script.
2. **One submission, preview-only.** There is exactly one `aws cloudformation deploy` in the
   script and it carries `--no-execute-changeset`. It prints the change set's ARN; the ARN that
   is described is the ARN that is executed, so there is no window between reading the plan and
   running it.
3. **`replaced_by_change_set`** reports every `Replacement: True` *and* every `Remove`, because
   renaming a logical resource is an Add and a Remove with no replacement flag and is also a new
   instance.
4. **`stage_stack` refuses** any non-empty result, deletes the change set and exits before
   mutating anything.
5. **`SeedDemoFixtureOnFirstBoot`** defaults to `"false"` and gates the boot seed twice: the
   `compose run seed` line is inside a conditional, and `PP_ALLOW_FIXTURE_RESET` in
   `migrate.env` is written from the same parameter — so a hand-run `compose run seed` on a host
   provisioned without a seed is refused by the application, not only by the bootstrap.
6. **`stage_host_image` names what dies before it asks**, and the confirmation is the id of the
   instance being destroyed: it cannot be guessed, cannot survive from a run against a different
   instance, and cannot be typed without having read the stack.
7. **`DeclaredHostAmiId` and `DemoFixtureSeededOnFirstBoot` are stack outputs**, so both
   non-release parameters are readable without describing the instance.
8. **Exact application identity is unchanged and still enforced**: the tag is the commit,
   a dirty tree is refused, and `host-image` passes `declared_image_tag` rather than
   `image_tag` so replacing the host cannot also move the release.

## 5. How the guards were checked

Twelve tests were added to `scripts/tests/test_deployment_definition.py` — nine that read the
definition and three that **run** it. The three source the script's function definitions without
its dispatch, put a stub `aws` on `PATH` that answers from a scenario and logs every call, and
call `stage_stack` and `stage_host_image` directly. No AWS call leaves the machine. They exist
because a static assertion can say the refusal is spelled correctly and cannot say the refusal
fires.

Each was checked by **mutation**: the protection was put back the way it was, the test was run,
and the file was restored from git. All twelve mutations were caught.

| mutation | caught by |
|---|---|
| a release resolves the newest AMI again | `test_a_release_passes_back_the_host_image_the_stack_already_declares` |
| the submission executes its own change set | `test_every_submission_builds_a_change_set_it_does_not_execute` |
| a release can arm the seed from the environment | `test_a_release_cannot_ask_for_a_seed_at_all` |
| a release never reads or refuses what its plan would replace | `test_a_release_refuses_a_change_set_that_would_replace_anything` |
| `all` replaces the host | `test_replacing_the_host_is_never_reached_by_a_release` |
| the confirmation need not name the instance | `test_replacing_the_host_requires_naming_the_instance_it_destroys` |
| *(run)* a release resolves the newest AMI again | `test_a_release_that_replaces_nothing_executes_the_plan_it_read` |
| *(run)* a release executes a plan that replaces the host | `test_a_release_whose_plan_replaces_the_host_is_actually_refused` |
| *(run)* the host is replaced with no confirmation | `test_replacing_the_host_without_the_confirmation_mutates_nothing` |
| the seed's own permission is unconditional again | `test_the_first_boot_seed_is_gated_on_the_parameter` |
| the first-boot seed is unconditional again | `test_the_first_boot_seed_is_gated_on_the_parameter` |
| a new instance seeds by default | `test_the_first_boot_seed_is_gated_on_the_parameter` |

The first run of the mutation check found one of the new tests **decorative**: it asserted
`--no-execute-changeset` was present in a function whose own comment describes that flag, so it
passed with the flag removed. It now strips comments before asserting, and the mutation is
caught. That is recorded rather than quietly fixed because it is the failure mode these tests
exist to avoid.

## 6. What this does not do, and what it costs

- **Fixture reset is still coupled to replacing the host.** The seed runs from `UserData`, and
  `UserData` runs once per instance, so the only way to reload the fixture through `deploy.sh`
  is to replace the instance with `PP_DEPLOY_SEED_ON_FIRST_BOOT=true`. A lighter path would mean
  running a command on the host from outside — SSM Run Command — which is a new AWS surface and
  a new permission, and was not built. G8's *"five complete deployed rehearsals from clean
  fixtures"* will therefore cost five host replacements, five certificate orders against a
  weekly duplicate limit, or a different mechanism than this one.
- **The change-set preview is a preview, not a lock.** Nothing prevents another hand from
  submitting a different change set between the description and the execution. The window is
  the length of one `describe-change-set`, and the ARN executed is the ARN described, so the
  plan cannot change underneath the check — but a *second* concurrent operator is not excluded.
- **`PP_DEMO_SESSION_ENABLED` is still unreachable from the control plane.** It is written into
  `api.env` by the bootstrap and `converge.sh` rewrites no env file, so changing it requires a
  replaced host. The template's comment claiming otherwise was found false on 2026-09-16 and is
  now corrected in place; the same claim in
  [p7.3-implementation-plan.md](p7.3-implementation-plan.md) section 9 is historical and was
  left as written, with the correction recorded here beside it.
- **Re-releasing the same commit still fails at the push**, because the ECR repositories are
  `IMMUTABLE`. That is pre-existing, unrelated to this change, and not a state hazard.
- **No IAM change was needed.** `CreateChangeSet`, `DescribeChangeSet`, `ExecuteChangeSet` and
  `DeleteChangeSet` are already in `deploy/policies/developer-role-delta.json`, because
  `aws cloudformation deploy` used all of them internally. No new AWS service is used.

## 7. What a live check would have to show

None of the following was done. It requires AWS credentials and the first two mutate.

1. **`./deploy/deploy.sh stack` against the live stack at HEAD.** Amazon has published
   `ami-07b9559027f889918` since the stack was created on `ami-0fa4996c14e7d501e`. Under the old
   script that run replaces the host. Under this one it must pass `ami-0fa4996c14e7d501e` back,
   build a change set that replaces nothing, and leave `i-087c742587f83d61d` untouched. That is
   the single observation that proves the fix on the real deployment.
2. **`./deploy/deploy.sh host-image` with no `PP_DEPLOY_REPLACE_HOST`.** It must print the
   replacement list, refuse, delete the change set unexecuted, and change nothing. This is a
   zero-mutation check of the destructive path: it creates and deletes one change set.
3. **The stack outputs** must carry `DeclaredHostAmiId` and `DemoFixtureSeededOnFirstBoot`, and
   the second must read `false`, after (1).

Until (1) has been run, the claim in this document is that the *definition* on disk cannot
express the defect — proved by mutation against tests — and not that the deployed stack has been
observed accepting it.

---

## 8. The same hole, one parameter wider

Date: 2026-09-17. No AWS resource was read, created, updated or deleted while this was written.

Sections 1–7 above are left exactly as they were written. This section records what they missed.

### 8.1 What was still open

The fix in section 4 stopped a release moving `HostAmiId`, because moving that one replaces the
instance and the replacement's first boot erased the database. It did not stop a release moving
any of the *other* parameters it submitted, and `create_stack_change_set` rebuilt all of them
from the caller's shell on every run:

```bash
"VpcId=${PP_DEPLOY_VPC_ID}"
"HostSubnetId=${PP_DEPLOY_HOST_SUBNET}"
"DatabaseSubnetIds=${PP_DEPLOY_DB_SUBNETS}"
"TlsHostname=${PP_DEPLOY_TLS_HOSTNAME:-}"
"AllowedIngressCidr=${PP_DEPLOY_INGRESS_CIDR:-0.0.0.0/0}"
"DatabaseBackupRetentionDays=${PP_DEPLOY_DB_BACKUP_DAYS:-7}"
```

So an ordinary `deploy.sh stack` against the existing stack submitted whatever those variables
happened to hold in the shell that ran it. Three of them are optional and fall back to a
default, which is the sharp edge:

| the shell | what a release submitted | effect |
|---|---|---|
| `PP_DEPLOY_INGRESS_CIDR` unset | `AllowedIngressCidr=0.0.0.0/0` | a deliberately narrowed ingress is reopened to the internet |
| `PP_DEPLOY_DB_BACKUP_DAYS=1` left over from a demo roll | `DatabaseBackupRetentionDays=1` | six days of point-in-time recovery discarded |
| `PP_DEPLOY_TLS_HOSTNAME` set from another experiment | a different certificate name | the name clients verify changes |
| a different VPC or subnets | new placement | the change set proposes to move the deployment |

**None of these is a `Replacement` or a `Remove`**, so `replaced_by_change_set` — which looks for
exactly those two and nothing else — would have passed every one of them through and executed
them. The guard added in section 4 was real, and the hole was beside it, in the same function.

This was found by reading the release path, not by an incident. Nothing in the table above is
claimed to have happened to the deployed stack.

### 8.2 The parameter-ownership model

Every parameter a submission sends now has exactly one owner.

| owner | parameters | where the value comes from |
|---|---|---|
| the submission | `ImageTag`, `HostAmiId`, `SeedDemoFixtureOnFirstBoot` | the three arguments to `create_stack_change_set`. A release passes the commit it pushed, the AMI the stack already declares, and a literal `false`. |
| the live stack | everything else — `Environment`, `VpcId`, `HostSubnetId`, `DatabaseSubnetIds`, `TlsHostname`, `AllowedIngressCidr`, `InstanceType`, `DatabaseInstanceClass`, `DatabaseStorageGiB`, `DatabaseBackupRetentionDays` | read back by `inherited_stack_parameters`, one `describe-stacks` call, on every submission against an existing stack |
| the caller's shell | the same infrastructure list — **and only on a first create** | `PP_DEPLOY_*`, which is now a provisioning input and not a release input |

`PP_DEPLOY_VPC_ID`, `PP_DEPLOY_HOST_SUBNET`, `PP_DEPLOY_DB_SUBNETS`, `PP_DEPLOY_INGRESS_CIDR`,
`PP_DEPLOY_TLS_HOSTNAME` and `PP_DEPLOY_DB_BACKUP_DAYS` appear exactly once each in the script,
inside the first-create branch, and a test asserts they appear nowhere else in the submission. An
existing-stack release does not read one of them, so there is nothing for a stale shell to move —
and the `need` checks moved onto that branch with them, because a release no longer requires
them to be set at all.

Changing an infrastructure value on a deployed stack is therefore a deliberate act: the value has
to be submitted through the template by a run that is not an ordinary release. That operation was
not built in this session and is not claimed to exist.

### 8.3 Two details that could have gone wrong quietly

- **`List<AWS::EC2::Subnet::Id>`.** `describe-stacks` returns `DatabaseSubnetIds` already
  comma-joined (`subnet-a,subnet-b`). It is passed back as one argv element with the comma
  inside it — the same spelling a first create uses and the one CloudFormation splits — which is
  why the overrides are built as a bash array and expanded quoted. A test asserts the joined form
  is submitted and that the space-separated form is not.
- **An empty inherited value.** The deployed stack derives its hostname from the address it
  allocated, so its `TlsHostname` is the empty string. It is submitted as `TlsHostname=` rather
  than skipped: an implementation that dropped empty values would hand that parameter to the
  template's default instead of to the stack, which is the same drift from the other direction.

An empty read is refused rather than treated as an empty stack. If the describe stops answering —
a permission lost, a query that no longer matches — the submission would otherwise carry the
three release parameters alone and let CloudFormation fall back for the rest, which is the defect
arriving by a different door.

### 8.4 One claim in section 4 that was not true when it was written

The comment on `stage_stack` said *"every RDS parameter is carried forward or read back rather
than recomputed here"*. `DatabaseBackupRetentionDays` was recomputed here, from
`PP_DEPLOY_DB_BACKUP_DAYS`. The sentence is true now. It is recorded rather than quietly left
correct, because the claim was made before the thing it claimed was so.

### 8.5 How this was checked

Ten tests were added and one was rewritten. Nine of the ten are behavioural: the stub's live
stack and the stub's shell disagree about **every** infrastructure value, and the tests read the
arguments `stage_stack` and `stage_host_image` actually submitted. No AWS call leaves the
machine. The rewritten one is `test_the_stack_stage_supplies_every_parameter_that_has_no_default`,
which asserted that a *release* names every parameter with no default; that is now the first
create's job and the test is
`test_a_first_create_supplies_every_parameter_that_has_no_default`.

| mutation | result |
|---|---|
| the submission rebuilds infrastructure from the environment | caught by six tests |
| the shell's values are appended over the inherited ones | caught by four tests |
| the inherited query stops excluding the release tag | caught |
| an empty parameter read is not refused | caught |
| an empty inherited value is dropped | caught |
| the inherited subnet list is split into separate arguments | **not expressible** — no value any of these parameters accepts may contain a space, so quoted and unquoted expansion are indistinguishable here. The joined form is asserted; the quoting is correct by construction and not proved by mutation. |

`./deploy/deploy.sh stack` has **not** been run against the live stack. Section 7's list of what a
live check would have to show is unchanged and still unperformed; a run of it would now also have
to show `AllowedIngressCidr`, `DatabaseSubnetIds` and `DatabaseBackupRetentionDays` submitted as
the stack declares them rather than as the shell holds them.

---

## 9. The live check, performed

Date: 2026-09-18. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything else
ran.

Section 7 said what a live check would have to show and that none of it had been done. It has now
been done, against the real `promisepatch-prod`. **Three change sets were created and all three were
deleted unexecuted. Nothing else was mutated.** No image was built or pushed, no stack was
updated, no instance was rebooted or replaced, no fixture was reset, no IAM was touched.

### 9.1 The live state, before and after

Identical in every field, read before the first change set and again after the last deletion.

| | before | after |
|---|---|---|
| stack status | `UPDATE_COMPLETE` | `UPDATE_COMPLETE` |
| stack last updated | `2026-09-16T16:40:40Z` | `2026-09-16T16:40:40Z` |
| `ImageTag` | `b62779d6e975` | `b62779d6e975` |
| `HostAmiId` | `ami-0fa4996c14e7d501e` | `ami-0fa4996c14e7d501e` |
| `AllowedIngressCidr` | `0.0.0.0/0` | `0.0.0.0/0` |
| `DatabaseBackupRetentionDays` | `1` | `1` |
| `DatabaseSubnetIds` | `subnet-06892e46df75ae5b6,subnet-0c8ed66d49566ba6e` | unchanged |
| `TlsHostname` | empty | empty |
| `HostInstanceId` | `i-087c742587f83d61d` | `i-087c742587f83d61d` |
| EC2 `ImageId` / launch time | `ami-0fa4996c14e7d501e` / `2026-09-13T18:33:33Z` | unchanged |
| RDS `DbiResourceId` / status | `db-U2JWQBTINX6W6GAB56EOTHOCSM` / `available` | unchanged |
| SSM `image-tag` | `b62779d6e975` | `b62779d6e975` |
| change sets on the stack | none | none |

`/healthz` still answers `b62779d6e975`, so the stack, SSM and the running host name the same
commit after the check as before it.

### 9.2 What the release path did against real AWS

`deploy.sh stack` itself was **not** run, and the reason is this document's own model rather than
caution: HEAD is `86bee22f3a5d`, its image was never pushed -- ECR holds `b62779d6e975` as the
newest tag in both repositories -- so a release at HEAD would have moved the CloudFormation
`ImageTag` to a commit SSM and the host do not name and no image exists for. Instead the script's
own functions were sourced without its dispatch, the same way the behavioural tests do it, and
driven against the live account with the tag the stack already declares. Every function exercised
is the shipped one.

- **`release_host_ami_id` returned `ami-0fa4996c14e7d501e`** -- the value the stack declares --
  while `latest_host_ami_id` returned `ami-07b9559027f889918` in the same run. The hazard is live
  and the fix holds against it. That is section 7 item 1, minus the execution.
- **`inherited_stack_parameters` read back all ten infrastructure parameters** from the real
  `describe-stacks`, including `TlsHostname` as an empty value and `DatabaseSubnetIds` as one
  comma-joined field. Both section 8.3 concerns behave on real CLI output.
- **The change set AWS built carried the live values, not the shell's.**
  `DatabaseBackupRetentionDays=1` is the proof that matters: the shell running the check had no
  `PP_DEPLOY_DB_BACKUP_DAYS`, so the pre-8.2 script would have submitted the default `7` and
  silently discarded six days of point-in-time recovery. It submitted `1`.
  `SeedDemoFixtureOnFirstBoot=false` was submitted literally.
- **A deliberately drifted shell moved nothing.** A third change set was built with all six
  variables set to values that disagree with the live stack -- `PP_DEPLOY_VPC_ID`,
  `PP_DEPLOY_HOST_SUBNET`, `PP_DEPLOY_DB_SUBNETS`, `PP_DEPLOY_INGRESS_CIDR=203.0.113.4/32`,
  `PP_DEPLOY_TLS_HOSTNAME=drift.example.com` and `PP_DEPLOY_DB_BACKUP_DAYS=7`. CloudFormation
  reported the submission carried `vpc-033f9da8cac696679`, the live subnets, `0.0.0.0/0`, an
  empty `TlsHostname` and `1`: not one of the six reached the template. That is the whole of
  section 8.2 holding on the real service rather than against a stub, and it is the case where
  the pre-8.2 script would have narrowed live ingress, renamed the certificate, moved the
  deployment to another VPC and discarded six days of point-in-time recovery -- none of which is
  a `Replacement` or a `Remove`, so nothing in the release path would have refused it. The change
  set was deleted unexecuted.
- **The ARN parse works on real CLI output.** `aws cloudformation deploy --no-execute-changeset`
  printed its ARN inside the command it suggests, the `grep -o` in `create_stack_change_set`
  recovered it, and `describe-change-set` accepted it.

### 9.3 What the live check found that no test could

Section 7 predicted the change set would replace nothing. **It did not.** Real CloudFormation
answered:

```
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation  Replacement: Conditional
Modify  AWS::EC2::Instance        Host                  Replacement: Conditional
```

with `Host.UserData` at `RequiresRecreation: Conditionally` and the association's `InstanceId` at
`Always`. Two things follow, and the second is a defect.

1. **A release against this stack does propose to touch the host**, because the template on disk
   changed `UserData` -- that is the seed gate from section 4 itself. Gating the seed is a
   `UserData` edit, and `UserData` is a recreation-capable property, so the fix that stops a
   replacement reseeding the database cannot land without a run that may replace the host. That is
   a real cost of the design and it was not noticed when sections 1-8 were written.
2. **`Replacement` is not a boolean, and the guard treated it as one.** It is `True`, `False` or
   `Conditional`, the last meaning CloudFormation cannot decide in advance.
   `replaced_by_change_set` matched `True` and `Remove` only, so it returned *nothing* for the
   plan above: `stage_stack` would have printed "the change set replaces and removes nothing" and
   executed a plan AWS had just said may destroy the instance. The protection section 4 claims --
   "a change set that would replace or remove any resource is refused" -- did not hold against the
   real service.

The stub could not find this. It answers `describe-change-set` with the *result* of the query
rather than with a payload the query runs against, so the filter expression was never executed by
any test, and the twelve mutations of section 5 all passed through it.

**Fixed in `fcd3c3b`.** `Conditional` now counts with `True` and `Remove` -- unknown fails closed
-- and the regression test runs the query, read out of `deploy.sh`, over the payload AWS actually
returned, so the filter itself is exercised rather than stubbed. Reverting the fix fails that
test. Re-run live against the same stack, the fixed guard refused:

```
REFUSED. would replace or remove: ElasticIpAssociation  Host
change set deleted unexecuted; nothing mutated
```

### 9.4 The host-image refusal, proved

`stage_host_image` was run with `PP_DEPLOY_REPLACE_HOST` unset and `PP_DEPLOY_SEED_ON_FIRST_BOOT`
unset. It printed what dies, refused, and deleted its change set:

```
  host image  ami-0fa4996c14e7d501e -> ami-07b9559027f889918
  release     b62779d6e975 (unchanged)
  instance    i-087c742587f83d61d is destroyed and replaced
  certificate ordered again for this name
  database    untouched; the new instance loads no fixture
  preserving 10 infrastructure parameters as the stack declares them
  the change set replaces or removes: ElasticIpAssociation  Host
error: set PP_DEPLOY_REPLACE_HOST=i-087c742587f83d61d to confirm the above. The change set was
deleted unexecuted and nothing was mutated.
```

The release tag was passed back unchanged rather than moved to HEAD, which is section 4 item 8
holding on the live stack. The confirmation variable was never set.

### 9.5 What is still unperformed

- **Section 7 item 1 is verified only up to execution.** A release was built, read and refused;
  none was executed, because HEAD's image is not in ECR and because the guard -- correctly --
  refuses this template against this stack. Proving an executed release replaces nothing needs a
  staged release whose template does not move `UserData`.
- **Section 7 item 3 is unverified.** `DeclaredHostAmiId` and `DemoFixtureSeededOnFirstBoot` are
  outputs of the template on disk, not of the deployed stack, which predates them. They appear
  only after a submission executes, and none did.
- **Nothing was executed, so no claim is made here about what an executed release does.**

## 10. The template needs a way in, and it is not a release

Date: 2026-09-18. Status: **closed locally. No AWS resource was read, created, updated or
deleted while this was written.** No image was built or pushed, no change set was created, no
instance was rebooted, no fixture was reset, no IAM was touched. Section 10.7 is the procedure
for doing this against AWS later; it has not been run.

### 10.1 Why the live stack cannot accept this template through `stack`

Section 9.3 found it and did not draw the consequence. Submitting the template in this checkout
against `promisepatch-prod` — the stack deployed on 2026-09-13 — changes `Host.UserData`,
because gating the first-boot seed (section 4 item 5) is a `UserData` edit. Real CloudFormation
answered:

```
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation  Replacement: Conditional
Modify  AWS::EC2::Instance        Host                  Replacement: Conditional
```

`Conditional` means the service cannot decide in advance whether the resource survives. Since
`fcd3c3b` the release guard counts that with `True` and `Remove`, and `stage_stack` refuses it
and deletes the change set unexecuted. That refusal is correct and must not be relaxed: an
application release that *may* destroy the instance is the hazard this entire document exists
for.

So both halves of that are true at once, and together they are a gap:

- the deployed stack **cannot** receive the current template through a release, and
- it **must not** be able to.

There was no third operation. `host-image` would have carried the template, which is exactly
the temptation this section refuses: see 10.4.

### 10.2 The operation model

Three operations submit `deploy/cloudformation/promisepatch.yaml`. They differ only in what
they are allowed to move, and nothing else about them is different.

| | `stack` (release) | `infrastructure` | `host-image` |
|---|---|---|---|
| reached by `all` | yes | **no** | no |
| `ImageTag` | this run's commit | **the stack's, read back** | the stack's, read back |
| `HostAmiId` | the stack's, read back | **the stack's, unless `PP_DEPLOY_HOST_AMI_ID` names another** | `PP_DEPLOY_HOST_AMI_ID`, else the newest AL2023 arm64 image |
| `SeedDemoFixtureOnFirstBoot` | literal `false` | **literal `false`** | `PP_DEPLOY_SEED_ON_FIRST_BOOT`, default `false` |
| infrastructure parameters | the stack's, read back | **the stack's, read back** | the stack's, read back |
| a plan that may replace anything | refused, always | **printed, then confirmed or refused** | printed, then confirmed |
| confirmation | none possible | `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE` | `PP_DEPLOY_REPLACE_HOST` |
| requires a clean tree | yes | no | no |

`infrastructure` is therefore the narrowest operation that can carry a template change: it
preserves the release, preserves the host image by default, forces the seed off, inherits every
infrastructure parameter off the live stack, and is unreachable from `stack`, `rollout` and
`all`. **An ordinary release is still incapable of changing infrastructure**, and nothing here
weakened that — the release path is byte-for-byte what section 9 verified live.

What it deliberately does **not** do: it does not reset or reload a fixture, and it cannot. The
seed is the literal `false` a release passes, not a variable, so `PP_DEPLOY_SEED_ON_FIRST_BOOT`
reaches it nowhere. `host-image` remains the only stage in this deployment that can reseed.

### 10.3 The destructive confirmation contract

1. The change set is built with `--no-execute-changeset` and described before anything runs —
   the same single submission every other stage uses.
2. `replaced_by_change_set` reports every `Replacement: True`, every `Replacement: Conditional`
   and every `Action: Remove`. There is one such detector in the script and all three stages
   read it.
3. **An empty result executes.** A plan that replaces and removes nothing is an ordinary
   template update and is applied without asking anything, because there is nothing to ask
   about.
4. **A non-empty result is printed in full, one logical id per line**, before it is judged, so
   what was refused is readable in the same output as the refusal.
5. **A plan naming any resource outside `Host` and `ElasticIpAssociation` is refused outright**,
   whatever is set. The confirmation is an instance id; it names the host and it names nothing
   else, so it cannot stand in for the `Database` — whose replacement is every case in the
   deployment. Widening that list is a code change somebody reads.
6. Otherwise the operator must set `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE` to the **exact**
   `HostInstanceId` the stack publishes. Not a boolean, not a yes, not a truncation, not another
   instance, not a different case. It cannot be guessed, cannot be typed without having read the
   stack, and cannot survive from a run against a different instance.
7. **It is not `PP_DEPLOY_REPLACE_HOST`.** Both confirmations name the same id, so one variable
   would mean an abandoned `host-image` attempt silently authorizes an infrastructure upgrade
   that may replace the host, and the reverse. Each variable is read by exactly one stage, and a
   test asserts neither stage mentions the other's.
8. Every refusal deletes the change set and exits non-zero. Nothing is mutated on any refusing
   path.

### 10.4 Whether `host-image` could have done this instead

It was audited before the stage was written, and it shares everything below the semantics:
`create_stack_change_set`, `replaced_by_change_set`, `discard_change_set`,
`execute_stack_change_set`, `stack_output`, `declared_image_tag`, `declared_host_ami_id`,
`stack_exists`. There is still one parameter list and one submission, and `host-image` was not
touched — a test pins its AMI resolution, its seed variable, its own confirmation and its
`EVERY CASE IS ERASED` warning, and its behavioural tests from `a2550d9` still pass unchanged.

What it could not share is the meaning. `host-image` exists to destroy the instance: it resolves
the newest AMI when given none, it is the one stage that can arm the seed, and it demands its
confirmation unconditionally because replacement is the point rather than a risk. Applying a
template through it would have meant an operation whose printed summary says the instance is
being destroyed when the intent was to change a `UserData` line, an AMI moving as a side effect
of a template upgrade, and the only reseeding path in the deployment sitting one variable away
from a routine operation. Overloading it to avoid a new stage would have cost exactly the
legibility the confirmation depends on.

### 10.5 What was checked, and how

`scripts/tests/test_deployment_definition.py`, 127 tests (102 before, 25 added). Eleven of the
new ones **run** a stage against the stubbed `aws` of `a2550d9` and read what was submitted,
executed or deleted; the rest assert structure, and one runs the guard's own JMESPath query —
taken out of `deploy.sh` — over the payload real CloudFormation returned.

Required properties, and where each is held:

| property | test |
|---|---|
| a release still refuses `True`, `Conditional` and `Remove` | `test_a_release_refuses_every_answer_that_is_not_a_flat_no` (parametrized over all three, against the real payload shape) |
| the upgrade preserves `ImageTag` | `test_an_infrastructure_upgrade_preserves_the_release_and_the_host_image` |
| it preserves `HostAmiId` by default | same, plus `test_an_infrastructure_upgrade_resolves_no_image_of_its_own` |
| the seed stays false | `test_an_infrastructure_upgrade_cannot_be_made_to_seed` (with `PP_DEPLOY_SEED_ON_FIRST_BOOT=true` set) |
| it cannot run through `all` | `test_an_infrastructure_upgrade_is_never_reached_by_a_release` |
| a destructive plan cannot execute unconfirmed | `test_..._refuses_unconfirmed`, `test_only_the_exact_instance_id_confirms_a_destructive_upgrade` (six wrong values), `test_the_host_image_confirmation_does_not_authorize_an_infrastructure_upgrade` |
| a non-destructive plan executes | `test_an_infrastructure_upgrade_preserves_the_release_and_the_host_image`, `test_a_confirmed_infrastructure_upgrade_executes_the_plan_it_read` |
| local drift changes no unrelated infrastructure | `test_an_infrastructure_upgrade_leaves_unrelated_infrastructure_where_it_is` |
| `host-image` is unchanged | `test_replacing_the_host_is_still_exactly_what_it_was`, plus every test from `a2550d9` |

**Mutation check.** Thirteen mutations were applied to `deploy/deploy.sh` one at a time and the
suite run against each; `deploy.sh` was restored after every one and verified identical.
**13/13 were caught by the file**, and **11/13 by the behavioural runs alone**. The two the
stubbed runs could not catch are not behaviours of a stage run and are held elsewhere: adding
`stage_infrastructure` to the `all` chain (a dispatch property, caught by the reachability test)
and dropping `Conditional` from the guard (caught by the query test, which executes the real
filter rather than a stub of it).

The mutations: confirmation inverted; confirmation accepting any non-empty value; confirmation
reading `PP_DEPLOY_REPLACE_HOST` instead of its own variable; allowlist widened to `Database`;
the unnameable-resource refusal disabled; `image_tag` instead of `declared_image_tag`; the AMI
defaulting to `latest_host_ami_id`; the seed read from the environment; the stage added to
`all`; the refusal no longer discarding its change set; `Conditional` dropped from the guard;
the plan never read; and a harmless plan made to demand a confirmation.

### 10.6 What this does not do

- **Nothing was run against AWS.** No change set for this template exists, the live stack still
  predates it, and no claim is made here about what an executed upgrade does.
- **No fixture reset was implemented**, deliberately. The deployed rehearsals G8 requires start
  from clean fixtures; how that reset is reached is a separate decision and is not this stage.
- **The `INFRASTRUCTURE_MAY_REPLACE` list is a policy, not a proof.** It bounds what the
  instance-id confirmation may authorize. A template change that legitimately needs to replace
  something else is refused until somebody widens the list in a commit, which is the intended
  cost.
- Section 9.5 is otherwise unchanged: an *executed* release is still unproved, and
  `DeclaredHostAmiId` / `DemoFixtureSeededOnFirstBoot` are still outputs of the template rather
  than of the deployed stack.

### 10.7 The migration procedure, for when it is run

Not performed. Run in this order, from a checkout of the commit whose template is being applied,
with the `promisepatch` profile and the identity of section 9 verified first.

1. **Read the live state and keep it.** Stack status, `Parameters`, `Outputs`, the EC2
   `ImageId` and launch time, the RDS `DbiResourceId` and status, and SSM `image-tag` — the
   table in section 9.1 is the shape. This is the before column; there must be an after one.
2. **Confirm the release is where it should be before touching the template.** The stack's
   `ImageTag`, SSM `image-tag` and `/healthz` must already name the same commit. An upgrade
   preserves whatever is declared, so a drifted release would be preserved too.
3. `./deploy/deploy.sh preflight` — zero mutation, and the gate the stage runs anyway.
4. `./deploy/deploy.sh infrastructure` with `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE` **unset**.
   This builds the change set, prints the release and host image it is preserving, prints every
   resource the plan may replace, refuses, and deletes the change set. Nothing is mutated.
5. **Read that output before doing anything else.** If it names anything beyond `Host` and
   `ElasticIpAssociation` the stage refuses outright and the template needs reading, not a
   confirmation. If it replaces nothing, step 4 will have executed it and the rest of this is
   only verification.
6. **Decide, knowing the cost.** A replaced `Host` means: a new instance; cloud-init runs again;
   a Let's Encrypt certificate ordered afresh for the same name against the weekly duplicate
   limit; and every container pulled again. The database outlives it and is **not** reseeded —
   the seed is `false` and cannot be otherwise from this stage. Confirm the ECR tag the stack
   declares still exists, or the new instance will boot and fail to pull.
7. Re-run with `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE=<the HostInstanceId printed in step 4>`.
   The stage rebuilds the change set, describes it again, and executes only that one.
8. **Read the after state**, against step 1: `HostInstanceId` (changed if the host was replaced),
   `ImageTag` (unchanged), `HostAmiId` (unchanged unless explicitly moved),
   `AllowedIngressCidr`, `DatabaseBackupRetentionDays`, `DatabaseSubnetIds` (all unchanged), the
   RDS `DbiResourceId` (**unchanged, or the database was replaced and the run failed whatever
   CloudFormation reported**), and `DemoFixtureSeededOnFirstBoot`, which should now exist as an
   output and read `false`.
9. `./deploy/deploy.sh smoke`, and check a case that existed before the upgrade still exists.
10. Record the before and after columns, the change set's printed plan, and anything that
    differed from this procedure, in a new section of this document.

---

## 11. The migration, performed

Date: 2026-09-18. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything
else ran and unchanged throughout.

Section 10.7 is the procedure and said it had not been run. It has now been run against the real
`promisepatch-prod`. **The stack was updated once, deliberately, through `infrastructure`.** No
image was built or pushed, no fixture was reset, no IAM was touched, `host-image` was never run,
and no host-image or seed variable was set at any point.

### 11.1 The gate before anything was submitted

Section 10.7 step 2 requires the three declarations to already name the same commit, because an
upgrade preserves whatever is declared and would have preserved a drift too.

| declaration | value |
|---|---|
| CloudFormation `ImageTag` | `b62779d6e975` |
| SSM `/promisepatch/prod/image-tag` | `b62779d6e975` |
| `/healthz` `image` | `b62779d6e975` |

They agreed, so the upgrade was allowed to proceed. `b62779d6e975` was also confirmed present in
**both** ECR repositories -- `promisepatch/backend` and `promisepatch/order-simulator` -- which is
step 6's requirement: had the host been replaced, it would have had an image to pull.

`./deploy/deploy.sh preflight` passed 9/9 tested requirements.

### 11.2 The live state, before and after

| | before | after |
|---|---|---|
| stack status | `UPDATE_COMPLETE` | `UPDATE_COMPLETE` |
| stack last updated | `2026-09-16T16:40:40Z` | `2026-09-18T10:19:07Z` |
| `ImageTag` | `b62779d6e975` | `b62779d6e975` |
| `HostAmiId` | `ami-0fa4996c14e7d501e` | `ami-0fa4996c14e7d501e` |
| `SeedDemoFixtureOnFirstBoot` | *(parameter absent)* | `false` |
| `AllowedIngressCidr` | `0.0.0.0/0` | `0.0.0.0/0` |
| `DatabaseBackupRetentionDays` | `1` | `1` |
| `DatabaseSubnetIds` | `subnet-06892e46df75ae5b6,subnet-0c8ed66d49566ba6e` | unchanged |
| `DatabaseInstanceClass` / `DatabaseStorageGiB` | `db.t4g.micro` / `20` | unchanged |
| `VpcId` / `HostSubnetId` / `InstanceType` | `vpc-033f9da8cac696679` / `subnet-0c8ed66d49566ba6e` / `t4g.small` | unchanged |
| `TlsHostname` | empty | empty |
| `HostInstanceId` | `i-087c742587f83d61d` | **`i-087c742587f83d61d`** |
| EC2 `ImageId` | `ami-0fa4996c14e7d501e` | unchanged |
| EC2 launch time | `2026-09-13T18:33:33Z` | **`2026-09-18T10:19:33Z`** |
| RDS `DbiResourceId` | `db-U2JWQBTINX6W6GAB56EOTHOCSM` | **unchanged** |
| RDS status / retention / created | `available` / `1` / `2026-09-11T11:19:51Z` | unchanged |
| SSM `image-tag` | `b62779d6e975` | `b62779d6e975` |
| `/healthz` `image` | `b62779d6e975` | `b62779d6e975` |
| `/healthz` `boot_id` | `1abf8699-...` | `663859da-...` |
| fixture `loaded_at` | `2026-09-13T18:35:32.148240Z` | **unchanged** |
| cases | 4 | **4, byte-identical** |
| ingress | 80 and 443 from `0.0.0.0/0` | unchanged |
| change sets on the stack | none | none |

Three **new** stack outputs appeared, which is section 7 item 3 and section 9.5's second open
item, both now closed: `DeclaredHostAmiId` = `ami-0fa4996c14e7d501e` (equal to the AMI declared
before the upgrade), and `DemoFixtureSeededOnFirstBoot` = `false`. Every pre-existing output --
`PublicUrl`, `PublicAddress`, `TlsHostname`, `McpEndpoint`, `WebhookEndpoint`,
`DatabaseEndpoint`, `HostInstanceId`, `DeclaredImageTag`, `LogGroupName`, `InstanceRoleArn` -- is
unchanged.

### 11.3 The plan, read before it ran

`./deploy/deploy.sh infrastructure` with `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE` **unset** printed
its plan, refused, deleted the change set unexecuted and exited non-zero:

```
  release     b62779d6e975 (unchanged)
  host image  ami-0fa4996c14e7d501e (unchanged)
  database    no fixture is loaded, no case is reset
  preserving 10 infrastructure parameters as the stack declares them
  THIS PLAN MAY REPLACE OR REMOVE:
    ElasticIpAssociation
    Host
  instance    i-087c742587f83d61d may be destroyed and replaced
error: set PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE=i-087c742587f83d61d to confirm the above.
```

A **separate** change set was then built through the shipped `create_stack_change_set`, described
in full, and deleted unexecuted -- because the stage's own printed list is filtered to what the
guard matches, and the question "is `Database` in this plan at all" has to be asked of the whole
plan. The complete answer was two changes and no others:

```
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation  Replacement: Conditional
          InstanceId  RequiresRecreation: Always        (ResourceReference)
Modify  AWS::EC2::Instance        Host                  Replacement: Conditional
          UserData    RequiresRecreation: Conditionally (DirectModification)
          UserData    RequiresRecreation: Conditionally (ParameterReference x2)
```

**`Database` does not appear in the change set** -- not as a modification, not as a replacement,
not as a removal. Every one of the ten inherited infrastructure parameters was submitted exactly
as the live stack declared it; the only parameter that differed from the live stack was
`SeedDemoFixtureOnFirstBoot`, which the stack did not have and which was submitted as the literal
`false`. The whole of the plan is the seed gate of section 4 item 5 -- a `UserData` edit -- and
the association's dependence on the instance it points at.

Only then was the run repeated with `PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE=i-087c742587f83d61d`.

### 11.4 The host was not replaced

The confirmation authorized a replacement. CloudFormation did not perform one. The stack events
for the update are four lines and name one resource:

```
2026-09-18T10:19:07Z  promisepatch-prod  UPDATE_IN_PROGRESS  User Initiated
2026-09-18T10:19:12Z  Host               UPDATE_IN_PROGRESS
2026-09-18T10:19:46Z  Host               UPDATE_COMPLETE
2026-09-18T10:19:50Z  promisepatch-prod  UPDATE_COMPLETE
```

`ElasticIpAssociation` was never touched -- its `Conditional` existed only because it references
an instance that *might* have been recreated, and once the instance was not, there was nothing to
do. `Conditional` resolved to *no recreation*: the instance id, the AMI, the root volume, the
Elastic IP and the certificate all survived.

**The instance was stopped and started in place.** `HostInstanceId` and `InstanceId` are the same
value they were, and the EC2 launch time moved from `2026-09-13T18:33:33Z` to
`2026-09-18T10:19:33Z` -- which is what a stop/start does and what a replacement would not have
done, because a replacement produces a different id. The restart is visible in the application as
a new `boot_id`. So applying a `UserData` change to a running instance cost a reboot-equivalent
and about forty seconds, and cost nothing else. That is a better outcome than section 10.7 step 6
prepared for, and the preparation was still correct: `Conditional` means the service would not say
in advance, so the cost had to be accepted before it could be found not to be charged.

The database was never at risk in this run and was not touched. `DbiResourceId` is the same
resource, and no snapshot was taken because `UpdateReplacePolicy: Snapshot` was never reached.

### 11.5 The demo world survived

This is the claim the whole document exists to protect, so it was checked against the data rather
than inferred from the absence of a seed.

- **All four pre-existing cases are still there**, with the same ids, states, headlines, reported
  text, `opened_at` and `updated_at`: `7e6319bc...` (`RESOLVED`), `637b8f53...` (`PLANNED`),
  `e66c5060...` (`NEEDS_HUMAN_INTERPRETATION`), `744f5f78...` (`RESOLVED`).
- **Two full case workspaces are byte-identical across the upgrade.** `/api/cases/{id}` was
  fetched before and after and hashed: `637b8f53...` is `7b9dd90ce530caae...` both times,
  `744f5f78...` is `e1ac192ed387b7da...` both times.
- **The fixture was not reloaded.** `/readyz` reports `loaded_at` `2026-09-13T18:35:32.148240Z`
  and digest `f6cb717c...` after the upgrade, both exactly as before. A reseed would have written
  a new `loaded_at`.

The reads were made through `/api/auth/demo-session`, which issues the read-only observer
principal of ADR-0013 and ADR-0016. Nothing in this verification could write.

`./deploy/deploy.sh smoke` passes **12/12** with `PP_MCP_BEARER_TOKEN` supplied, and 10/12 passed
with 2 skipped and **0 failed** without it. See 11.7.

### 11.6 An ordinary release now proposes nothing at all

Section 9.5's first open item -- *"proving an executed release replaces nothing needs a staged
release whose template does not move `UserData`"* -- is closed, without building or pushing an
image and without moving the deployment to an unstaged one. Two change sets were built through
the shipped release functions and both were deleted unexecuted.

- **Same release.** `create_stack_change_set` with the AMI `release_host_ami_id` returns and the
  tag the stack declares produced **no change set at all**: CloudFormation answered *"The
  submitted information didn't contain changes."* The template in this checkout and the deployed
  stack are now the same thing. That is zero infrastructure drift, stated by the service.
- **A genuine release.** The same submission with `ImageTag` moved to `acfdd975dd4d` -- a tag that
  really exists in both ECR repositories -- produced a change set whose resource-change list is
  **empty**. Not "no replacements": no resource changes whatsoever. `ImageTag` is referenced
  nowhere in `Host.UserData`; it reaches only the `DeclaredImageTag` output.
  `replaced_by_change_set`, the shipped guard, returned the empty string against it, so
  `stage_stack` would have printed *"the change set replaces and removes nothing; executing"*.
  Every other parameter was submitted as the live stack declares it.

In the same run `release_host_ami_id` returned `ami-0fa4996c14e7d501e` while `latest_host_ami_id`
returned `ami-0d50898f9b64253da` -- a *third* AL2023 arm64 image, newer than the
`ami-07b9559027f889918` of section 9. Amazon has now published two images since this stack was
created, the hazard of section 1 is live and growing, and a release still passes back the image
the stack declares.

Both verification change sets were deleted, as was the `FAILED` change-set object the empty
submission leaves behind. **The stack has no change sets.**

### 11.7 One defect the live run found, fixed in `4a3603f`

`./deploy/deploy.sh smoke` reported **10/12, 1 failed** on a healthy deployment, minutes after
the upgrade -- which is exactly the moment a spurious failure is read as damage. The failing check
was `origin-refused`: *"status 401, expected 403"*, which reads as "the deployed origin guard is
open".

It was not. The origin guard sits *behind* the bearer check, so an unauthenticated request is
refused `401` before the origin is ever considered. The shell running the check had no
`PP_MCP_BEARER_TOKEN`, so the check could not be performed at all -- and reported a verdict about
the deployment anyway. Its sibling `protocol-revision`, which depends on the same token, has
always reported `SKIPPED` with the reason; the module docstring even said *"that one check"*, and
there were two.

Supplying the token from SSM and re-running gave **12/12, 0 failed**, which is what proved the
deployment healthy and the check wrong.

`check_origin_refused` now skips with the same explicit reason, and the docstring names both
checks. A skip is still neither a pass nor silence: the run's exit code fails on any `FAILED`, so
a missing token cannot turn a broken deployment green. The regression test passes `None` as the
HTTP client on purpose -- a skip has to decide before it touches the network, so deleting the skip
turns the test into an `AttributeError` rather than a quiet pass. **The mutation was applied and
caught.**

### 11.8 What is still unperformed

- **The instance's `UserData` was not read back directly.** `ec2:DescribeInstanceAttribute` is
  not in the developer role and **IAM was not broadened to get it**. That the new gated `UserData`
  landed on the resource rests on CloudFormation's own `Host UPDATE_COMPLETE` with `UserData` in
  the change's scope, and on `DemoFixtureSeededOnFirstBoot` = `false` now being a stack output of
  the same parameter the bootstrap reads. Both are strong; neither is the bytes on the instance.
- **No replacement was exercised.** This upgrade was authorized to replace the host and did not.
  What a *replaced* instance does on its first boot with `SeedDemoFixtureOnFirstBoot=false` -- the
  thing the gate exists for -- is still proved only by the definition and its tests, not by an
  observed replacement.
- **Fixture reset is still coupled to replacing the host**, unchanged from section 6. G8's
  deployed rehearsals from clean fixtures still have no cheap path.
- **No release was executed.** The release path was proved to propose nothing; executing one needs
  an image built and pushed, which this run deliberately did not do.

# A release is not allowed to destroy the deployment

Date: 2026-09-17
Status: **closed locally. Nothing has been verified against AWS**, and section 7 says exactly
what a live check would have to show. No AWS resource was read, created, updated or deleted
while this was written.

> **Superseded on 2026-09-18 by [section 9](#9-the-live-check-performed).** The status line
> above is left as written. The live check has since been run against `promisepatch-prod`, it
> found a defect in the guard described in section 4 item 3, and section 9 records both what it
> proved and what it left unperformed.

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

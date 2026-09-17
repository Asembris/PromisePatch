# A release is not allowed to destroy the deployment

Date: 2026-09-17
Status: **closed locally. Nothing has been verified against AWS**, and section 7 says exactly
what a live check would have to show. No AWS resource was read, created, updated or deleted
while this was written.

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
  asserted; the second was not, and now is — it is the half a release could actually have
  reached.
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

Nine tests were added to `scripts/tests/test_deployment_definition.py`. Each was checked by
**mutation**: the protection was put back the way it was, the test was run, and the file was
restored. All nine mutations were caught.

| mutation | caught by |
|---|---|
| a release resolves the newest AMI again | `test_a_release_passes_back_the_host_image_the_stack_already_declares` |
| the submission executes its own change set | `test_every_submission_builds_a_change_set_it_does_not_execute` |
| a release can arm the seed from the environment | `test_a_release_cannot_ask_for_a_seed_at_all` |
| a release never reads or refuses what its plan would replace | `test_a_release_refuses_a_change_set_that_would_replace_anything` |
| `all` replaces the host | `test_replacing_the_host_is_never_reached_by_a_release` |
| the confirmation need not name the instance | `test_replacing_the_host_requires_naming_the_instance_it_destroys` |
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

# The stale stack declaration, and the guard that closes it

**Status: CLOSED. The deployed stack, the SSM parameter the host converges on and the running
process all name `acfdd975dd4d`. `deploy.sh` can no longer complete a release that leaves
CloudFormation naming a different commit.**

## 1. What was wrong

There are three separate declarations of which image is deployed, and each is written by a
different `deploy.sh` stage:

| declaration | written by | read by |
|---|---|---|
| ECR tag on the pushed image | `images` | the host's `docker compose pull` |
| `/promisepatch/prod/image-tag` in SSM | `config` | `converge.sh`, at every boot |
| the `ImageTag` stack parameter | `stack` | nothing at runtime; published as `DeclaredImageTag` |

Every stage is separately runnable, which is deliberate — a failed deploy is resumed rather
than restarted. The consequence was not: `images`, `config` and `rollout` is a complete,
working release path that never touches CloudFormation. The host pulls the new image, comes up
on it, and `stage_rollout` polls `/healthz` until it names the tag — but the tag it compares
against is `image_tag`, recomputed from the checkout. Two of the three answers came from the
same place, and the third was never asked.

So the release succeeded and the stack went on declaring the previous commit. The only
comparison against CloudFormation lived in `stage_smoke`, which is a separate stage a release
need not run.

That is the state the deployment was found in on 2026-09-14:

```
CloudFormation ImageTag       87f3a13f26a9     (stack last updated 2026-09-13T18:33Z)
SSM /promisepatch/prod/image-tag  acfdd975dd4d  (version 3, written 2026-09-13T21:52Z)
/healthz image                acfdd975dd4d
```

The application was healthy throughout. Nothing a user could reach was wrong; the control
plane's answer to "what is deployed" was.

## 2. Why it matters more than it looks

`DeclaredImageTag` is the value `deploy.sh smoke` hands the smoke check as
`PP_EXPECTED_IMAGE_TAG`, and `check_deployed_image` is the one check that distinguishes a
deployment that is *up* from one that is *current*. While the stack was stale that check was
comparing the host against a commit it was right not to be running: it would have failed a
correct deployment, and — had the drift run the other way — passed an incorrect one. A
verification instrument that names the wrong expected value is worse than none, because it is
believed.

## 3. The guard

`require_image_declarations_agree` reads both declarations it does not own — the stack
parameter and the SSM parameter — back from AWS, and compares them with the tag the release
names. `stage_rollout` calls it **before** the reboot, so:

* `images`, `config`, `rollout` without `stack` now fails, naming the stack's value and the
  release's, rather than converging the host and leaving the stack behind;
* `images`, `rollout` without `config` fails immediately instead of rebooting the host onto the
  old image and then spending fifteen minutes timing out on `/healthz`;
* `all` is unaffected, because by the time `rollout` runs all three agree.

`stage_smoke` compares the stack parameter with the SSM parameter before it spends the HTTP
checks. That third answer is invisible to `deployment_smoke.py`, which runs from outside AWS
against a public origin and makes no AWS call at all — a stack and a host that agree while SSM
names something else are one reboot away from disagreeing, and only the deploy script can see
it.

Neither change weakens anything, adds a permission, or alters what is deployed.

## 4. How the live stack was aligned

Not with `deploy.sh stack`. That stage recomputes the tag from `HEAD` — which was
`122bebb9cd93`, a commit whose image was never pushed — and re-resolves `HostAmiId` to the
newest Amazon Linux 2023 arm64 image, which differs from the deployed `ami-0fa4996c14e7d501e`
and would have **replaced the instance**. Running it would have turned a declaration mismatch
into a host rebuild.

Instead, one change set against the deployed template, changing one parameter:

```
aws cloudformation create-change-set --stack-name promisepatch-prod \
  --change-set-name align-image-tag-acfdd975dd4d --change-set-type UPDATE \
  --use-previous-template --capabilities CAPABILITY_NAMED_IAM \
  --role-arn arn:aws:iam::265243686715:role/PromisePatchDeploymentRole \
  --parameters ImageTag=acfdd975dd4d, every other parameter UsePreviousValue=true
```

`--use-previous-template` is the important flag: the template is the one already deployed, so
nothing in the repository's working copy could reach the stack, and every parameter other than
`ImageTag` carries its live value forward explicitly rather than by omission.

The change set came back `CREATE_COMPLETE` / `AVAILABLE` with **`"Changes": []`** — zero
resource changes, which is the whole proof that no EC2 instance, database, subnet, security
group or address was touched. `ImageTag` is referenced only by the template's `Metadata` and by
the `DeclaredImageTag` output; no resource reads it. Executing it produced no resource events
at all, only `UPDATE_IN_PROGRESS` → `UPDATE_COMPLETE_CLEANUP_IN_PROGRESS` → `UPDATE_COMPLETE`,
six seconds end to end.

## 5. After

| | before | after |
|---|---|---|
| CloudFormation `ImageTag` | `87f3a13f26a9` | `acfdd975dd4d` |
| `DeclaredImageTag` output | `87f3a13f26a9` | `acfdd975dd4d` |
| SSM `/promisepatch/prod/image-tag` | `acfdd975dd4d` | `acfdd975dd4d` |
| `/healthz` image | `acfdd975dd4d` | `acfdd975dd4d` |
| Host instance | `i-087c742587f83d61d` | `i-087c742587f83d61d` |
| Host launch time | `2026-09-13T18:33:33Z` | `2026-09-13T18:33:33Z` |
| `/healthz` `boot_id` | `1b32a22f-50af-495b-be18-48e19db06cb8` | `1b32a22f-50af-495b-be18-48e19db06cb8` |
| `HostAmiId` | `ami-0fa4996c14e7d501e` | `ami-0fa4996c14e7d501e` |

The unchanged `boot_id` is the stronger of the two host facts: the instance was not replaced,
and it was not even restarted.

Backend image digest for the aligned tag:

```
promisepatch/backend:acfdd975dd4d
  sha256:dfac4c8476d19ba1d0094e1adcbbec0541e11120590290720709dfeaffa33321
```

The ECR repository is `IMMUTABLE`, so that tag names that digest permanently and cannot be
made to name another one.

Deployment smoke against `https://184.194.40.87.sslip.io`: **12/12 passed, 0 failed, 0
skipped**, including `deployed-image` — which now compares the host against the commit the
stack actually declares.

## 6. What is asserted on disk

In `scripts/tests/test_deployment_definition.py`, offline, no AWS call:

* `test_the_stack_is_told_the_tag_this_run_pushed` — `images`, `config` and `stack` derive the
  tag from the same `image_tag`, and the stack stage passes it as `ImageTag`.
* `test_the_stack_stage_supplies_every_parameter_that_has_no_default` — every parameter with no
  default is supplied by the same run, so a release cannot drop one; every override names a
  parameter the template declares; and the tag is never passed alone.
* `test_a_release_cannot_leave_the_stack_declaring_the_previous_commit` — the guard exists, the
  rollout calls it, and it runs before the reboot rather than after.
* `test_the_smoke_stage_refuses_a_deployment_whose_declarations_disagree` — the smoke stage
  reads both declarations, compares them, and does so before the HTTP checks.
* `test_a_release_is_a_parameter_write_and_a_reboot_rather_than_a_new_instance` — the rollout
  contains no stack deploy, no `update-stack`, no `run-instances` and no termination, because
  `UserData` runs once per instance and a release must not depend on it running again.

The two guard tests were run against the pre-fix `deploy.sh` and both fail there.

## 7. What this did not do

No image was built or pushed. No database was reseeded. No instance was replaced, stopped or
rebooted. No IAM policy was changed and no permission was requested. The account holds exactly
one CloudFormation stack, `promisepatch-prod`; every call made here named that stack,
`/promisepatch/prod/*`, `promisepatch/backend`, or the instance the stack owns. The unrelated
CareLoop project was not read and not touched.

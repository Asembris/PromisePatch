#!/usr/bin/env bash
#
# Deploy the P6 stack, in the only order that works, and refuse to start if the identity in
# this shell cannot finish. Every stage is separately runnable so a failed deploy is resumed
# rather than restarted.
#
#   ./deploy/deploy.sh preflight   # zero mutation; the gate every other stage runs first
#   ./deploy/deploy.sh secrets     # create the SSM parameters, never overwrite one
#   ./deploy/deploy.sh registry    # create the two ECR repositories, idempotently
#   ./deploy/deploy.sh images      # build for arm64 and push, tagged with the commit SHA
#   ./deploy/deploy.sh config      # upload the compose file, the Caddyfile and the tag
#   ./deploy/deploy.sh stack       # release: move the image tag, replace nothing
#   ./deploy/deploy.sh rollout     # reboot the host onto the image this commit pushed
#   ./deploy/deploy.sh smoke       # prove the deployed endpoints from outside
#   ./deploy/deploy.sh all         # the above, in that order
#
# And one stage that is not a release and is never reached by one:
#
#   ./deploy/deploy.sh host-image  # replace the instance, on purpose, after showing what dies
#
# **An application release moves the image tag and nothing else.** It passes back the host image
# the stack already declares, passes a literal `false` for the demo seed, and refuses any change
# set that would replace or remove a resource. That is not a style choice: `ImageId` is a
# replacement property on `AWS::EC2::Instance`, `stage_stack` used to resolve the newest AL2023
# image at every run, and the instance's first boot ends in `compose run seed`, which replaces
# every domain row in a database that outlives the host. So the first release after Amazon
# published a new image would have replaced the host and erased every case on it. That was
# proved rather than argued -- a change set built that way reported `Replacement: True` on the
# Host and the EIPAssociation, and was deleted unexecuted -- and it is recorded in
# docs/head-redeploy-2026-09-16.md section 7 and closed by docs/non-destructive-release.md.
#
# The order is not arbitrary. The registry has to exist before an image can be pushed, the
# images and the configuration have to exist before the host boots or its first `compose pull`
# fails, and the secrets have to exist before the stack resolves the database password.
#
# **The PP_DEPLOY_* placement, ingress, TLS and sizing variables below provision a stack. They
# do not release one.** Once the stack exists, every infrastructure parameter a submission sends
# is read back off that stack, so a shell that has lost `PP_DEPLOY_INGRESS_CIDR`, still carries
# `PP_DEPLOY_DB_BACKUP_DAYS=1` from a demo roll, or points at a different VPC cannot move any of
# them by running a release. Changing one on a deployed stack means saying so where the value can
# be read -- a submission through the template with the new value -- and not letting a stale
# shell decide. `create_stack_change_set` is where that split lives.
#
# Required for a first create, and read by nothing an existing-stack release does:
#   PP_DEPLOY_VPC_ID          an existing VPC
#   PP_DEPLOY_HOST_SUBNET     a subnet with a route to an internet gateway
#   PP_DEPLOY_DB_SUBNETS      two or more subnet ids, comma separated, in different zones
# Optional, and likewise first-create only where they name infrastructure:
#   PP_DEPLOY_TLS_HOSTNAME    the name the certificate is issued for and clients verify.
#                             Unset, the stack derives `<elastic-ip>.sslip.io` -- a real public
#                             name that already resolves to the address the stack allocates, so
#                             a first deploy needs no record pointed at an address that does not
#                             exist yet. The certificate is publicly trusted either way.
#   PP_DEPLOY_ENV             default prod
#   PP_DEPLOY_REGION          default us-east-1
#   PP_DEPLOY_INGRESS_CIDR    default 0.0.0.0/0
#   PP_DEPLOY_ACME_CONTACT    an address a certificate problem should reach
#   PP_DEPLOY_DB_BACKUP_DAYS  days of automated database backups, default 7. An account on the
#                             AWS Free Tier plan cannot have 7 and RDS refuses the create; set
#                             it to what the plan allows, and record that it was lowered.
# Read only by `host-image`, and by nothing a release runs:
#   PP_DEPLOY_HOST_AMI_ID     the image to move to. Unset, the newest AL2023 arm64 one.
#   PP_DEPLOY_SEED_ON_FIRST_BOOT
#                             `true` loads the demo fixture on the new instance's first boot,
#                             which erases every case in the database. Default false. This is
#                             the only way a deployment reseeds, and it is deliberately not
#                             reachable from `stack`, `rollout` or `all`.
#   PP_DEPLOY_REPLACE_HOST    the id of the instance being destroyed, typed back to confirm it.
#
# TLS verification is never weakened anywhere in this script or anywhere in this repository:
# a test enumerates every spelling of "trust whatever certificate turns up" and fails on any of
# them. Downloads are pinned to https and TLS 1.2 or better.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${1:-}"

ENVIRONMENT="${PP_DEPLOY_ENV:-prod}"
REGION="${PP_DEPLOY_REGION:-us-east-1}"
STACK_NAME="promisepatch-${ENVIRONMENT}"
PREFIX="/promisepatch/${ENVIRONMENT}"
TEMPLATE="${REPO_ROOT}/deploy/cloudformation/promisepatch.yaml"
DEPLOYMENT_ROLE_NAME="PromisePatchDeploymentRole"

say () { printf '\n=== %s\n' "$*"; }
die () { printf 'error: %s\n' "$*" >&2; exit 1; }

need () {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "$name is required; see the header of this script"
}

account_id () { aws sts get-caller-identity --region "$REGION" --query Account --output text; }

# One output of the deployed stack. Read back rather than reconstructed: the public name may
# have been derived from an address the stack allocated, and the instance id is whatever the
# last update left behind.
stack_output () {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

stack_exists () {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" >/dev/null 2>&1
}

# The newest Amazon Linux 2023 arm64 image, resolved here rather than by the template.
# `AWS::SSM::Parameter::Value<...>` on the AWS-published AMI parameter is the tidier spelling and
# is the one this template used to carry; it needs the CloudFormation *service role* to hold
# `ssm:GetParameters` on `parameter/aws/service/*`, which the deployment role does not have and
# is not being given -- that role is scoped to this project's own parameters. The submitting
# identity already holds `ec2:DescribeImages`, so the same fact is read with the permission that
# exists. Latest by creation date, never a pinned id: an AMI in git goes stale silently.
#
# **A release never calls this.** Only `host-image` and a first create do; see
# `release_host_ami_id` for why that distinction is the whole point.
latest_host_ami_id () {
  aws ec2 describe-images --region "$REGION" --owners amazon     --filters "Name=name,Values=al2023-ami-2023.*-kernel-6.1-arm64"                "Name=state,Values=available"                "Name=architecture,Values=arm64"     --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text
}

# What CloudFormation currently declares the host was built from.
declared_host_ami_id () {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Parameters[?ParameterKey=='HostAmiId'].ParameterValue" --output text
}

# The image an application release passes: the one the stack already carries, never a newer one.
#
# This is the fix. `ImageId` is a replacement property on `AWS::EC2::Instance`, and `stage_stack`
# used to resolve the newest image at every run -- so the first release after Amazon published an
# AL2023 build replaced the host, ran cloud-init again against the database the old host left
# behind, and erased every case in it. Reading the value back means a release cannot move it at
# all. Moving it is `stage_host_image`, which says what dies before it asks.
#
# A stack that does not exist yet has nothing to preserve and no cases to lose, so a first create
# resolves the newest image. That is the only path in this script that does so implicitly.
release_host_ami_id () {
  local ami
  if stack_exists; then
    ami="$(declared_host_ami_id)"
    [[ "$ami" == ami-* ]] || die "the stack declares no HostAmiId; run host-image to set one"
  else
    ami="$(latest_host_ami_id)"
    [[ "$ami" == ami-* ]] || die "no Amazon Linux 2023 arm64 image was found in $REGION"
  fi
  printf '%s' "$ami"
}

# The image tag is the commit, and only ever the commit. A dirty tree is refused rather than
# tagged, because "which version is deployed" has to have one answer -- G8 verifies the
# deployed version rather than an old image, and a tag that does not name a commit makes that
# question unanswerable.
image_tag () {
  git -C "$REPO_ROOT" diff --quiet && git -C "$REPO_ROOT" diff --cached --quiet \
    || die "working tree is dirty; commit before deploying so the image tag names a commit"
  git -C "$REPO_ROOT" rev-parse --short=12 HEAD
}

# What CloudFormation currently declares this deployment runs, and what the host will converge
# on at its next boot. Both are read back rather than recomputed here, because the question
# below is whether the control plane, the parameter the host reads and this release give the
# same answer, and taking two of the three from this checkout would answer a different one.
declared_image_tag () {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Parameters[?ParameterKey=='ImageTag'].ParameterValue" --output text
}

converged_image_tag () {
  aws ssm get-parameter --region "$REGION" --name "${PREFIX}/image-tag" --query Parameter.Value --output text
}

# There are three separate declarations of which image is deployed -- the stack parameter, the
# SSM parameter the host converges on, and the commit whose image was pushed -- and a release is
# only a release when all three name the same one. Each stage succeeds on its own, so before
# this existed a run of `images`, `config` and `rollout` without `stack` converged the host onto
# a new image and left CloudFormation declaring the previous commit: the host served the new
# build, `/healthz` agreed with this checkout, and nothing compared either with the stack until
# somebody thought to run `smoke`. That drift was observed on the deployed stack, which declared
# `87f3a13f26a9` while SSM, the host and `/healthz` all said `acfdd975dd4d`.
require_image_declarations_agree () {
  local tag="$1" declared converged
  converged="$(converged_image_tag)"
  declared="$(declared_image_tag)"
  [[ "$converged" == "$tag" ]] || die "SSM names $converged, this release names $tag; run config"
  [[ "$declared" == "$tag" ]] || die "the stack declares $declared, this release names $tag; run stack"
  printf '  the stack, SSM and this release all name %s\n' "$tag"
}

# ------------------------------------------------------------------------------------ stages

stage_preflight () {
  say "preflight (zero mutation)"
  ( cd "$REPO_ROOT" && uv run python scripts/aws_preflight.py --region "$REGION" ) \
    || die "preflight failed. Nothing was created. See docs/p6.1-deployment-preflight.md"
}

# Secrets are generated here and never printed, never committed, never passed as a stack
# parameter and never baked into an image. `--no-overwrite` is the important flag: a re-run
# must not rotate a live database password out from under a running instance.
stage_secrets () {
  say "secrets"
  local generated
  put_secret () {
    local name="$1" value="$2"
    if aws ssm get-parameter --region "$REGION" --name "${PREFIX}/${name}" >/dev/null 2>&1; then
      printf '  kept     %s\n' "${PREFIX}/${name}"
      return
    fi
    aws ssm put-parameter --region "$REGION" --name "${PREFIX}/${name}" \
      --type SecureString --value "$value" --tags Key=Project,Value=promisepatch \
      --no-overwrite >/dev/null
    printf '  created  %s\n' "${PREFIX}/${name}"
  }
  for name in db-master-password db-app-password mcp-bearer-token session-secret \
              order-webhook-secret internal-service-token demo-worker-password \
              demo-owner-password; do
    generated="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    put_secret "$name" "$generated"
  done
  if [[ -n "${PP_DEPLOY_ACME_CONTACT:-}" ]]; then
    put_secret acme-contact "$PP_DEPLOY_ACME_CONTACT"
  fi
}

# Outside the stack on purpose: the registry must exist before the first push and should
# outlive `delete-stack`, so a redeploy does not re-push every layer.
stage_registry () {
  say "registry"
  local repository
  for repository in promisepatch/backend promisepatch/order-simulator; do
    if aws ecr describe-repositories --region "$REGION" \
         --repository-names "$repository" >/dev/null 2>&1; then
      printf '  kept     %s\n' "$repository"
      continue
    fi
    aws ecr create-repository --region "$REGION" --repository-name "$repository" \
      --image-tag-mutability IMMUTABLE \
      --image-scanning-configuration scanOnPush=true \
      --tags Key=Project,Value=promisepatch >/dev/null
    aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$repository" \
      --lifecycle-policy-text '{"rules":[{"rulePriority":1,"description":"keep the last 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' \
      >/dev/null
    printf '  created  %s\n' "$repository"
  done
}

stage_images () {
  say "images"
  local account tag registry
  account="$(account_id)"; tag="$(image_tag)"
  registry="${account}.dkr.ecr.${REGION}.amazonaws.com"
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$registry"
  # The host is Graviton, so the images are built for arm64 whatever this machine is. The
  # build itself is the repository's own Dockerfile with its own pinned lockfile: deployment
  # changes where the image runs, not what is in it.
  # `--build-arg PP_IMAGE_TAG` is what makes the running image name itself: the API reports
  # it at /healthz, and the smoke check compares that with the tag the stack says it
  # deployed. A host serving an older image than the stack declares is then a failed check
  # rather than something somebody has to think to look for.
  docker buildx build --platform linux/arm64 \
    --file "${REPO_ROOT}/docker/Dockerfile.backend" \
    --secret "id=extra_ca,src=${REPO_ROOT}/docker/env/extra-ca.crt" \
    --build-arg "PP_IMAGE_TAG=${tag}" \
    --tag "${registry}/promisepatch/backend:${tag}" --push "$REPO_ROOT"
  docker buildx build --platform linux/arm64 \
    --file "${REPO_ROOT}/docker/Dockerfile.simulator" \
    --secret "id=extra_ca,src=${REPO_ROOT}/docker/env/extra-ca.crt" \
    --tag "${registry}/promisepatch/order-simulator:${tag}" --push "$REPO_ROOT"
  printf '  pushed at tag %s\n' "$tag"
}

# The composition and the TLS configuration live in git and are uploaded as parameters, so the
# host re-reads both at every boot and a change to either is a parameter write plus a restart
# rather than an instance replacement. Standard-tier parameters cap at 4096 bytes; the test
# suite asserts both files stay under it.
stage_config () {
  say "config"
  local compose caddyfile
  compose="${REPO_ROOT}/deploy/compose/docker-compose.deploy.yml"
  caddyfile="${REPO_ROOT}/deploy/compose/Caddyfile"
  for file in "$compose" "$caddyfile"; do
    [[ "$(wc -c < "$file")" -le 4096 ]] || die "$file exceeds the 4096-byte parameter limit"
  done
  aws ssm put-parameter --region "$REGION" --name "${PREFIX}/compose" --type String \
    --value "$(cat "$compose")" --overwrite >/dev/null
  aws ssm put-parameter --region "$REGION" --name "${PREFIX}/caddyfile" --type String \
    --value "$(cat "$caddyfile")" --overwrite >/dev/null
  # The image tag is configuration too, and it is the one the host actually converges
  # on: the stack parameter records what this deploy intended, and this is what the next
  # boot reads. Written by the same run that pushed the image, from the same commit.
  aws ssm put-parameter --region "$REGION" --name "${PREFIX}/image-tag" --type String --value "$(image_tag)" --overwrite >/dev/null
  printf '  uploaded %s/{compose,caddyfile,image-tag}\n' "$PREFIX"
}

# Every parameter the live stack declares except the three a submission owns, spelled as
# `Key=Value` overrides and read back off CloudFormation rather than rebuilt from this shell.
#
# This is the second half of the same fix as `release_host_ami_id`, and it closes the same class
# of hole one parameter wider. `HostAmiId` was the parameter whose drift was *proved* to replace
# the host, but it was never the only infrastructure parameter a release submitted: `VpcId`,
# `HostSubnetId`, `DatabaseSubnetIds`, `TlsHostname`, `AllowedIngressCidr` and
# `DatabaseBackupRetentionDays` were all rebuilt from the caller's environment at every run. So a
# shell that had lost `PP_DEPLOY_INGRESS_CIDR` since the last deploy silently reopened 443 to the
# internet on the next release; a shell whose `PP_DEPLOY_DB_BACKUP_DAYS` still said `1` from a
# demo roll silently cut the database's recovery window; and a shell pointed at a different VPC
# submitted a change set that moves the deployment. None of those is a `Replacement` or a
# `Remove` on the host, so `replaced_by_change_set` -- which only ever looked for those -- would
# have let every one of them through. The guard was real and the hole was beside it.
#
# An ordinary release owns release state and nothing else. What the deployment *is* -- where it
# runs, who may reach it, how long its backups live -- is whatever the live stack says it is, and
# this shell does not get a vote.
#
# `--output text` on a two-element projection gives one `key<TAB>value` line per parameter, and
# an empty `ParameterValue` (`TlsHostname` on the deployed stack) gives an empty second field,
# which is the value to pass back. A `List<AWS::EC2::Subnet::Id>` comes back already joined --
# `DatabaseSubnetIds` reads `subnet-a,subnet-b` -- and goes back as one argv element with the
# comma inside it, which is the same spelling a first create passes and the one CloudFormation
# splits. Quoting is what makes that true, so the overrides are built as an array.
inherited_stack_parameters () {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
    --query "Stacks[0].Parameters[?ParameterKey!='ImageTag' && ParameterKey!='HostAmiId' && ParameterKey!='SeedDemoFixtureOnFirstBoot'].[ParameterKey,ParameterValue]" \
    --output text
}

# Build the change set and do not execute it. One parameter list, filled in by both stages that
# submit this template -- a release and a host replacement -- because two copies of the list
# would drift out of step exactly where it is most expensive to be wrong.
#
# The list has two halves and they have different owners:
#
#   * **Submission-owned**, always named here explicitly: `ImageTag`, `HostAmiId` and
#     `SeedDemoFixtureOnFirstBoot`. These are the three arguments, and they are the only three
#     things either stage is allowed to move. A release passes the tag it pushed, the AMI the
#     stack already declares and a literal `false`.
#   * **Infrastructure-owned**: everything else. On an existing stack these are read back off
#     that stack, so the values submitted are the values already live whatever this shell holds.
#     Only a first create reads them from the environment, because then there is no stack to
#     read and nothing yet to preserve.
#
# So `PP_DEPLOY_*` is a *provisioning* input, not a release input, and a release does not read
# one. That is also why the `need` checks live on the first-create branch: an existing-stack
# release neither requires those variables nor is affected by them.
#
# `--role-arn` is what keeps the human's standing privilege small: the resource-creating
# permissions belong to a role only CloudFormation can assume, so every mutation arrives through
# a template that was submitted and can be read back.
#
# Prints the change set's ARN, or nothing at all when the submission changes nothing. Nothing
# else may be printed to stdout from here: the caller captures it and reads an ARN out of it.
create_stack_change_set () {
  local ami="$1" seed="$2" tag="$3" account output key value
  local -a overrides=()
  if stack_exists; then
    while IFS=$'\t' read -r key value; do
      [[ -n "$key" ]] || continue
      overrides+=("${key}=${value}")
    done < <(inherited_stack_parameters)
    # An empty read means the describe failed or the query stopped matching, not that the stack
    # has no parameters -- and submitting the release parameters alone would then hand every
    # infrastructure value back to whatever CloudFormation falls back to. Refuse instead.
    [[ ${#overrides[@]} -gt 0 ]] \
      || die "the stack declares no parameters to preserve; refusing to submit a release that would reset its infrastructure"
    printf '  preserving %s infrastructure parameters as the stack declares them\n' \
      "${#overrides[@]}" >&2
  else
    need PP_DEPLOY_VPC_ID; need PP_DEPLOY_HOST_SUBNET
    need PP_DEPLOY_DB_SUBNETS
    overrides=(
      "Environment=${ENVIRONMENT}"
      "VpcId=${PP_DEPLOY_VPC_ID}"
      "HostSubnetId=${PP_DEPLOY_HOST_SUBNET}"
      "DatabaseSubnetIds=${PP_DEPLOY_DB_SUBNETS}"
      "TlsHostname=${PP_DEPLOY_TLS_HOSTNAME:-}"
      "AllowedIngressCidr=${PP_DEPLOY_INGRESS_CIDR:-0.0.0.0/0}"
      "DatabaseBackupRetentionDays=${PP_DEPLOY_DB_BACKUP_DAYS:-7}"
    )
  fi
  overrides+=("ImageTag=${tag}" "HostAmiId=${ami}" "SeedDemoFixtureOnFirstBoot=${seed}")
  account="$(account_id)"
  output="$(aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-file "$TEMPLATE" \
    --role-arn "arn:aws:iam::${account}:role/${DEPLOYMENT_ROLE_NAME}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-execute-changeset \
    --no-fail-on-empty-changeset \
    --tags Project=promisepatch \
    --parameter-overrides "${overrides[@]}")"
  # `deploy --no-execute-changeset` prints the change set's ARN inside the command it tells you
  # to run next, and nothing else in its output looks like one. There is no `--change-set-name`
  # option to ask for a name instead, and taking the newest one from `list-change-sets` would be
  # guessing which change set this run made.
  printf '%s' "$output" | grep -o 'arn:aws[a-z-]*:cloudformation:[^ ]*:changeSet/[^ ]*' | tail -1 || true
}

# What the change set says will happen to existing resources, before any of it happens.
#
# This is the only thing in this script that can see an instance replacement coming. It was read
# by hand on 2026-09-16 -- a change set built with a newly-resolved AMI reported `Replacement:
# True` on the Host and on the EIPAssociation, and was deleted rather than executed, which is the
# only reason the cases on that host still exist. This is that step written down, so the next
# release does not depend on somebody thinking to do it.
#
# A `Remove` counts as well as a `Replacement`, because renaming a logical resource is reported
# as an Add and a Remove with no replacement flag at all, and that is also a new instance.
#
# `Conditional` counts too, and that one was found against the live stack on 2026-09-18 rather
# than by reading the script. `Replacement` is not a boolean: CloudFormation answers `True`,
# `False` or `Conditional`, the last meaning it cannot decide in advance and the resource may be
# replaced when the change set runs. A release submitting a template whose `UserData` differs
# from the deployed one gets exactly that -- `Host` with `RequiresRecreation: Conditionally` and
# `ElasticIpAssociation` with `Always` on its `InstanceId` -- and a detector matching only `True`
# returned nothing, so `stage_stack` printed "replaces and removes nothing" and would have
# executed a plan that may destroy the instance. Unknown fails closed: a maybe is refused, and
# replacing the host on purpose is still `host-image`.
replaced_by_change_set () {
  aws cloudformation describe-change-set --region "$REGION" --change-set-name "$1" \
    --query "Changes[?ResourceChange.Replacement=='True' || ResourceChange.Replacement=='Conditional' || ResourceChange.Action=='Remove'].ResourceChange.LogicalResourceId" \
    --output text
}

discard_change_set () {
  aws cloudformation delete-change-set --region "$REGION" --change-set-name "$1" >/dev/null
}

# The change set described above is the one executed here. There is no window between reading
# the plan and running it, and no second submission that could resolve anything differently.
execute_stack_change_set () {
  aws cloudformation execute-change-set --region "$REGION" --change-set-name "$1"
  aws cloudformation wait "$2" --region "$REGION" --stack-name "$STACK_NAME"
}

# An application release. It moves the image tag and nothing else.
#
# The host image is whatever the stack already declares, the demo seed is a literal `false` that
# no environment variable can turn on from here, and a change set that would replace or remove
# any resource is refused and deleted rather than executed. So a release cannot replace the host,
# cannot pick up a newer AMI, cannot run the bootstrap again and cannot reseed the database --
# not by policy but because the values that would do any of those are not reachable from this
# stage. The database is preserved the same way: every RDS parameter is carried forward or read
# back rather than recomputed here, and a change set proposing to replace anything is refused
# before it executes.
stage_stack () {
  say "stack (application release)"
  local tag ami change_set replaced waiter
  tag="$(image_tag)"; ami="$(release_host_ami_id)"
  waiter="stack-update-complete"; stack_exists || waiter="stack-create-complete"
  printf '  release %s, host image %s (unchanged), seed false\n' "$tag" "$ami"
  change_set="$(create_stack_change_set "$ami" "false" "$tag")"
  if [[ -z "$change_set" ]]; then
    printf '  the stack already declares this release; nothing to change\n'
  else
    replaced="$(replaced_by_change_set "$change_set")"
    if [[ -n "$replaced" && "$replaced" != "None" ]]; then
      discard_change_set "$change_set"
      die "this release would replace or remove: ${replaced}. A release moves the image tag and nothing else, so the change set was deleted unexecuted and nothing was mutated. Run host-image if replacing the instance is what you want."
    fi
    printf '  the change set replaces and removes nothing; executing\n'
    execute_stack_change_set "$change_set" "$waiter"
  fi
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs' --output table
}

# Replacing the host, deliberately. Not a release, and not reachable from one.
#
# This is the expensive operation and the destructive one: a new EC2 instance, a first boot that
# runs the bootstrap again, and a Let's Encrypt certificate ordered afresh for the same name
# against a weekly duplicate limit. With the seed on it is also the only thing in this deployment
# that reseeds, and reseeding erases every case in a database that outlives the host.
#
# Everything it destroys is named before it is asked for, and the confirmation is the id of the
# instance being destroyed -- which cannot be guessed, cannot be left set from a previous run,
# and cannot be typed without having read the stack.
stage_host_image () {
  say "host-image (replaces the instance)"
  local ami instance seed tag change_set replaced
  stack_exists || die "there is no stack to give a host image to; run stack first"
  ami="${PP_DEPLOY_HOST_AMI_ID:-$(latest_host_ami_id)}"
  [[ "$ami" == ami-* ]] || die "no Amazon Linux 2023 arm64 image was found in $REGION"
  instance="$(stack_output HostInstanceId)"
  [[ -n "$instance" && "$instance" != "None" ]] || die "the stack publishes no HostInstanceId"
  seed="${PP_DEPLOY_SEED_ON_FIRST_BOOT:-false}"
  [[ "$seed" == "true" || "$seed" == "false" ]] \
    || die "PP_DEPLOY_SEED_ON_FIRST_BOOT is ${seed}; it is true or false"
  # Not `image_tag`: this stage builds and pushes nothing, so it must not move the release. It
  # passes back what the stack already declares, and a host replacement changes the host alone.
  tag="$(declared_image_tag)"
  printf '  host image  %s -> %s\n' "$(declared_host_ami_id)" "$ami"
  printf '  release     %s (unchanged)\n' "$tag"
  printf '  instance    %s is destroyed and replaced\n' "$instance"
  printf '  certificate ordered again for this name\n'
  if [[ "$seed" == "true" ]]; then
    printf '  DATABASE    the demo fixture is reloaded: EVERY CASE IS ERASED\n'
  else
    printf '  database    untouched; the new instance loads no fixture\n'
  fi
  change_set="$(create_stack_change_set "$ami" "$seed" "$tag")"
  if [[ -z "$change_set" ]]; then
    printf '  the stack already declares this host image and this seed; nothing to change\n'
    return
  fi
  replaced="$(replaced_by_change_set "$change_set")"
  printf '  the change set replaces or removes: %s\n' "${replaced:-nothing}"
  if [[ "${PP_DEPLOY_REPLACE_HOST:-}" != "$instance" ]]; then
    discard_change_set "$change_set"
    die "set PP_DEPLOY_REPLACE_HOST=${instance} to confirm the above. The change set was deleted unexecuted and nothing was mutated."
  fi
  execute_stack_change_set "$change_set" "stack-update-complete"
  printf '  replaced; the new instance is %s\n' "$(stack_output HostInstanceId)"
  printf '  run smoke to check what it serves\n'
}

# A release, once the image is pushed and the parameters are written: reboot the host, which
# runs `converge.sh`, which re-reads the composition, the TLS configuration and the image tag
# and pulls what it finds. Then read the deployed `/healthz` until it names the commit that
# was pushed -- because "the stack updated" and "the host is serving that build" are
# different claims, and the first was true while the second was false for a whole release.
stage_rollout () {
  say "rollout"
  local tag instance origin served deadline
  tag="$(image_tag)"
  instance="$(stack_output HostInstanceId)"
  origin="$(stack_output PublicUrl)"
  [[ -n "$instance" && "$instance" != "None" ]] || die "the stack publishes no HostInstanceId"
  # Before the reboot, not after it, and against the two declarations this stage does not
  # own: a rollout whose stack still names the previous commit is the drift itself, and a
  # rollout whose SSM parameter still names it would converge the host onto the old image
  # and then spend fifteen minutes failing to explain why.
  require_image_declarations_agree "$tag"
  printf '  rebooting %s onto %s\n' "$instance" "$tag"
  aws ec2 reboot-instances --region "$REGION" --instance-ids "$instance"
  deadline=$((SECONDS + 900))
  while (( SECONDS < deadline )); do
    sleep 15
    served="$(curl -fsS --max-time 10 "${origin}/healthz" 2>/dev/null | python -c 'import json,sys; print(json.load(sys.stdin).get("image") or "")' 2>/dev/null || true)"
    if [[ "$served" == "$tag" ]]; then
      printf '  serving %s\n' "$tag"
      return
    fi
    printf '  waiting, serving %s\n' "${served:-nothing yet}"
  done
  die "the host serves ${served:-nothing} after fifteen minutes; this deploy named $tag"
}

# The origin is read back from the stack rather than reconstructed here, because the name
# may have been derived from an address the stack allocated -- asking the stack is the only
# way to be sure the thing being smoke-checked is the thing that was deployed.
stage_smoke () {
  say "smoke"
  local origin declared converged
  origin="$(stack_output PublicUrl)"
  [[ -n "$origin" && "$origin" != "None" ]] || die "the stack publishes no PublicUrl"
  # What the stack says it deployed, so the check can compare it with what the deployed
  # process says it is. Read from the stack rather than from this shell: the question is
  # whether the host runs what the stack declares, and taking both sides from this checkout
  # would answer a different one.
  declared="$(declared_image_tag)"
  # And the third declaration, which no HTTP check can see. The host converges on the SSM
  # parameter, so a stack and a host that agree while SSM names something else are one
  # reboot away from disagreeing. Compared here rather than inside the smoke script, which
  # is run from outside AWS against a public origin and makes no AWS call at all.
  converged="$(converged_image_tag)"
  [[ "$converged" == "$declared" ]] || die "the stack declares $declared, SSM names $converged"
  printf '  origin %s, declared %s\n' "$origin" "$declared"
  ( cd "$REPO_ROOT" && PP_EXPECTED_IMAGE_TAG="$declared" uv run python scripts/deployment_smoke.py --base-url "$origin" )
}

case "$STAGE" in
  preflight) stage_preflight ;;
  secrets)   stage_preflight; stage_secrets ;;
  registry)  stage_preflight; stage_registry ;;
  images)    stage_preflight; stage_images ;;
  config)    stage_preflight; stage_config ;;
  stack)     stage_preflight; stage_stack ;;
  rollout)   stage_preflight; stage_rollout ;;
  smoke)     stage_smoke ;;
  # Deliberately absent from `all`. Replacing the host is not part of any release, and an
  # operation that destroys an instance and can erase every case is one somebody asks for by
  # name.
  host-image) stage_preflight; stage_host_image ;;
  all)
    stage_preflight
    stage_secrets
    stage_registry
    stage_images
    stage_config
    stage_stack
    stage_rollout
    stage_smoke
    ;;
  *) die "usage: $0 {preflight|secrets|registry|images|config|stack|rollout|smoke|all|host-image}" ;;
esac

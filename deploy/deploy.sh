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
#   ./deploy/deploy.sh config      # upload the compose file and the Caddyfile
#   ./deploy/deploy.sh stack       # create or update the CloudFormation stack
#   ./deploy/deploy.sh smoke       # prove the deployed endpoints from outside
#   ./deploy/deploy.sh all         # the above, in that order
#
# The order is not arbitrary. The registry has to exist before an image can be pushed, the
# images and the configuration have to exist before the host boots or its first `compose pull`
# fails, and the secrets have to exist before the stack resolves the database password.
#
# Required environment:
#   PP_DEPLOY_VPC_ID          an existing VPC
#   PP_DEPLOY_HOST_SUBNET     a subnet with a route to an internet gateway
#   PP_DEPLOY_DB_SUBNETS      two or more subnet ids, comma separated, in different zones
#   PP_DEPLOY_TLS_HOSTNAME    the name the certificate is issued for and clients verify
# Optional:
#   PP_DEPLOY_ENV             default prod
#   PP_DEPLOY_REGION          default us-east-1
#   PP_DEPLOY_INGRESS_CIDR    default 0.0.0.0/0
#   PP_DEPLOY_ACME_CONTACT    an address a certificate problem should reach
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

# The image tag is the commit, and only ever the commit. A dirty tree is refused rather than
# tagged, because "which version is deployed" has to have one answer -- G8 verifies the
# deployed version rather than an old image, and a tag that does not name a commit makes that
# question unanswerable.
image_tag () {
  git -C "$REPO_ROOT" diff --quiet && git -C "$REPO_ROOT" diff --cached --quiet \
    || die "working tree is dirty; commit before deploying so the image tag names a commit"
  git -C "$REPO_ROOT" rev-parse --short=12 HEAD
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
  docker buildx build --platform linux/arm64 \
    --file "${REPO_ROOT}/docker/Dockerfile.backend" \
    --secret "id=extra_ca,src=${REPO_ROOT}/docker/env/extra-ca.crt" \
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
  printf '  uploaded %s/{compose,caddyfile}\n' "$PREFIX"
}

stage_stack () {
  say "stack"
  need PP_DEPLOY_VPC_ID; need PP_DEPLOY_HOST_SUBNET
  need PP_DEPLOY_DB_SUBNETS; need PP_DEPLOY_TLS_HOSTNAME
  local account tag
  account="$(account_id)"; tag="$(image_tag)"
  # `--role-arn` is what keeps the human's standing privilege small: the resource-creating
  # permissions belong to a role only CloudFormation can assume, so every mutation arrives
  # through a template that was submitted and can be read back.
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-file "$TEMPLATE" \
    --role-arn "arn:aws:iam::${account}:role/${DEPLOYMENT_ROLE_NAME}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    --tags Project=promisepatch \
    --parameter-overrides \
      "Environment=${ENVIRONMENT}" \
      "VpcId=${PP_DEPLOY_VPC_ID}" \
      "HostSubnetId=${PP_DEPLOY_HOST_SUBNET}" \
      "DatabaseSubnetIds=${PP_DEPLOY_DB_SUBNETS}" \
      "TlsHostname=${PP_DEPLOY_TLS_HOSTNAME}" \
      "AllowedIngressCidr=${PP_DEPLOY_INGRESS_CIDR:-0.0.0.0/0}" \
      "ImageTag=${tag}"
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs' --output table
}

stage_smoke () {
  say "smoke"
  need PP_DEPLOY_TLS_HOSTNAME
  ( cd "$REPO_ROOT" && uv run python scripts/deployment_smoke.py \
      --base-url "https://${PP_DEPLOY_TLS_HOSTNAME}" )
}

case "$STAGE" in
  preflight) stage_preflight ;;
  secrets)   stage_preflight; stage_secrets ;;
  registry)  stage_preflight; stage_registry ;;
  images)    stage_preflight; stage_images ;;
  config)    stage_preflight; stage_config ;;
  stack)     stage_preflight; stage_stack ;;
  smoke)     stage_smoke ;;
  all)
    stage_preflight
    stage_secrets
    stage_registry
    stage_images
    stage_config
    stage_stack
    stage_smoke
    ;;
  *) die "usage: $0 {preflight|secrets|registry|images|config|stack|smoke|all}" ;;
esac

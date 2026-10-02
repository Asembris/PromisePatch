#!/bin/bash
# Parameter-only change set against the PREVIOUSLY DEPLOYED template (post-intake-release.md,
# deploy-stack-cannot-release-anymore): ImageTag moves, every other parameter UsePreviousValue.
# usage: changeset.sh create <tag> | changeset.sh execute <name>
set -euo pipefail
S="C:/Users/Asembris/AppData/Local/Temp/claude/D--PromisePatch/ba76b5dc-8abb-4b46-86ce-4382022b4e5e/scratchpad"
export AWS_PROFILE=promisepatch AWS_DEFAULT_REGION=us-east-1 AWS_CA_BUNDLE="$S/ca.pem" AWS_MAX_ATTEMPTS=10 AWS_RETRY_MODE=adaptive
STACK=promisepatch-prod
case "$1" in
create)
  tag="$2"; name="bridge-release-$tag"
  current=$(aws cloudformation describe-stacks --stack-name $STACK --query "Stacks[0].Parameters[?ParameterKey=='ImageTag'].ParameterValue" --output text)
  echo "current ImageTag=$current intended=$tag"
  params=$(aws cloudformation describe-stacks --stack-name $STACK --query 'Stacks[0].Parameters[].ParameterKey' --output text)
  args=()
  for k in $params; do
    if [ "$k" = ImageTag ]; then args+=("ParameterKey=ImageTag,ParameterValue=$tag")
    else args+=("ParameterKey=$k,UsePreviousValue=true"); fi
  done
  echo "parameters submitted: ${#args[@]}"
  aws cloudformation create-change-set --stack-name $STACK --change-set-name "$name" \
    --change-set-type UPDATE --use-previous-template --capabilities CAPABILITY_NAMED_IAM \
    --parameters "${args[@]}" --query Id --output text
  aws cloudformation wait change-set-create-complete --stack-name $STACK --change-set-name "$name" || true
  aws cloudformation describe-change-set --stack-name $STACK --change-set-name "$name" \
    --query '{Status:Status,Exec:ExecutionStatus,Reason:StatusReason,Changes:Changes,Params:Parameters[].[ParameterKey,ParameterValue]}' --output json
  ;;
execute)
  name="$2"
  changes=$(aws cloudformation describe-change-set --stack-name $STACK --change-set-name "$name" --query 'length(Changes)' --output text)
  status=$(aws cloudformation describe-change-set --stack-name $STACK --change-set-name "$name" --query 'Status' --output text)
  echo "status=$status resource_changes=$changes"
  [ "$status" = CREATE_COMPLETE ] && [ "$changes" = 0 ] || { echo "REFUSED: not an empty plan"; exit 1; }
  aws cloudformation execute-change-set --stack-name $STACK --change-set-name "$name"
  aws cloudformation wait stack-update-complete --stack-name $STACK
  aws cloudformation describe-stacks --stack-name $STACK --query 'Stacks[0].{S:StackStatus,U:LastUpdatedTime}' --output json
  aws cloudformation describe-stack-events --stack-name $STACK --max-items 8 \
    --query 'StackEvents[].[Timestamp,LogicalResourceId,ResourceStatus]' --output text
  ;;
esac

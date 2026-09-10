# The three policy documents, and why each grant is there

These files are **valid IAM policy documents and nothing else** — `Version` and `Statement`, no
prose. That is deliberate and was a correction: an earlier version carried a top-level
`Comment` array explaining each statement, which reads well and cannot be applied. IAM's policy
grammar admits only `Version`, `Id` and `Statement` at the top level and a fixed set of keys
inside a statement, so an extra key is a `MalformedPolicyDocument` rather than an ignored
annotation. A policy file that has to be hand-edited before it can be pasted is a policy file
whose reviewed form is not the form that gets applied. The explanation therefore lives here.
`test_every_policy_is_a_valid_iam_document` enforces the separation.

Substitute `ACCOUNT_ID` before applying. `deployment-role-trust.json` contains no account
reference and needs no substitution.

## Applying them

1. `deployment-role-trust.json` + `deployment-role-policy.json` → create
   `PromisePatchDeploymentRole`. This is the only principal in the account that may create the
   deployment's resources, and only CloudFormation can assume it.
2. `developer-role-delta.json` → attach to `PromisePatchDeveloperRole` as a customer-managed or
   inline policy. Suggested name: `PromisePatchDeploymentEntry`.
3. `uv run python scripts/aws_preflight.py` — it must print `9/9 required allowed`.

## `developer-role-delta.json` — what a person gets

The smallest delta that unblocks the deployment. Nothing here creates a compute, database,
network or IAM resource directly: the only mutation path is a CloudFormation stack whose name
starts with `promisepatch-`, executed with the deployment service role. A person holding this
cannot create an EC2 instance, an RDS database or an IAM role by hand, and cannot pass any role
other than that one service role to any service other than CloudFormation.

`AdministratorAccess` is not requested. No `PassRole` is wildcarded. Every statement is scoped
by resource except the four that cannot be, and each of those is either a read or has no
resource form:

| Sid | Why it is what it is |
|---|---|
| `StackIsTheOnlyMutationPath` | scoped to `stack/promisepatch-*/*`; every resource is created through it |
| `StackListAndValidateAreAccountWideReads` | `ListStacks` and `ValidateTemplate` answer account-level questions and have no resource form |
| `HandTheStackItsServiceRoleAndNothingElse` | `PassRole` on exactly one role, with `iam:PassedToService` pinned to CloudFormation |
| `PushImagesBecauseAPushIsNotAStackAction` | an image push is not a CloudFormation action, and the registry must exist before the host boots |
| `RegistryAuthTokenHasNoResourceForm` | `ecr:GetAuthorizationToken` is account-level by definition |
| `WriteTheSecretsTheStackAndHostRead` | scoped to `parameter/promisepatch/*` |
| `EncryptAndDecryptThoseSecureStringsOnly` | `*` fenced by `kms:ViaService = ssm.us-east-1.amazonaws.com`, so the key is reachable only through SSM |
| `FindTheLogGroupAtAll` | see below |
| `ReadTheDeployedLoopBackOut` | everything that can read a log *line*, scoped to `/promisepatch/*` |
| `RestartTheHostToProveTheCaseOutlivesIt` | scoped by `ec2:ResourceTag/Project = promisepatch`; the restart-durability proof needs it |
| `ReachTheHostWithoutInboundSshOrAKeyPair` | Session Manager, so the host needs no inbound SSH and no key pair |
| `PreflightAndDeployReadsOnly` | `*`, and every action in it is a read |
| `NeverBroadenIamFromHere` | explicit `Deny` on every IAM-creating action |
| `NeverPassAnyOtherRoleAnywhere` | explicit `Deny` with `NotResource`, which no later `Allow` can override |

### Why `logs:DescribeLogGroups` is the one `*` that is not a plain read of ours

It is evaluated against the account, not against a group: it answers "which log groups exist",
a question with no single resource. Scoping it to `log-group:/promisepatch/*` denies it outright
— which is exactly what the first version of this policy did, and the deployment would have
been unable to find its own log group. It is separated into its own statement so that the
breadth is visible and bounded: it grants the ability to see that log groups exist and what
they are named, and no ability to read a log line. Every action that can read content —
`DescribeLogStreams`, `GetLogEvents`, `FilterLogEvents`, `StartLiveTail` — stays scoped to
`/promisepatch/*` in the statement next to it.

## `deployment-role-policy.json` — what CloudFormation gets

The resource-creating permissions, reachable only through a submitted template. Deleting the
stack is the whole undo and the template is the whole audit trail.

Two things it cannot do, both enforced by explicit `Deny` that no `Allow` overrides: it cannot
create an IAM principal other than `PromisePatchInstanceRole` and that role's instance profile,
and it cannot pass any role to anything except that one role to EC2. It also carries three caps
so a mistake cannot become expensive or exposed — `ec2:RunInstances` denied outside
`t4g.small`/`t4g.medium`/`t3a.small`/`t3a.medium`, `rds:CreateDBInstance` denied outside
`db.t4g.micro`/`db.t4g.small`, and both RDS write actions denied when
`rds:PubliclyAccessible` is true — and `iam:AttachRolePolicy` is denied for any managed policy
except `AmazonSSMManagedInstanceCore`.

## `deployment-role-trust.json` — who may assume it

An ordinary CloudFormation service role: the CloudFormation service principal, and nothing
else. No person, no other service, no other account.

**This file matches what exists in AWS**, which is the reason it looks plainer than it used to.
An earlier draft added `aws:SourceAccount` and `aws:SourceArn` conditions restricting it to
`promisepatch-` stacks; those were deliberately dropped when the role was actually created. The
conditions are a confused-deputy guard, and for a CloudFormation service role in a single
account that guard already sits somewhere better: the only way this role reaches a stack is for
a principal to pass it, and `iam:PassRole` in the developer delta is restricted to this exact
role with `iam:PassedToService` equal to `cloudformation.amazonaws.com`, with a companion
`Deny` on passing anything else. **The control moved; it was not removed.**

Carrying a stricter policy in git than the one in the account would have been worse than
either, because a reader would trust the file and be wrong. `docs/p6.1-deployment-preflight.md`
records the same reconciliation.

## The runtime role is not here

`PromisePatchInstanceRole` is created by `deploy/cloudformation/promisepatch.yaml`, inline,
where the resources it names are defined. It is not duplicated into this directory: two copies
of one policy is how they drift.

# AWS friction log

PromisePatch was deployed on AWS during the hackathon: one EC2 host (Amazon Linux 2023, arm64)
running every process in a container, a private encrypted RDS PostgreSQL instance, SSM Parameter
Store for configuration, ECR for images, CloudWatch Logs, and Amazon Bedrock (Nova 2 Lite through
a US cross-Region inference profile) for the one language-understanding call. The stack is
defined in CloudFormation and released by [`deploy/deploy.sh`](../deploy/deploy.sh).

Every entry below comes from hands-on implementation and deployment work, is backed by a
committed record in this repository, and states the workaround we actually used. Issues caused
by our own scripts, and issues specific to our Windows workstation, are excluded; they are
listed at the end with the reason for each.

---

## 1. A container on EC2 gets `NoCredentialsError` with no hint that the IMDS hop limit is the cause

**Task.** Call Bedrock from a worker process running in a Docker container on EC2, using the
instance role, with IMDSv2 required.

**Friction.** The failure gives no indication of where the credential chain stopped or why.

**Expected.** When the SDK reaches the instance metadata service but cannot complete the IMDSv2
token exchange, the error says so, and ideally names `HttpPutResponseHopLimit` as a likely cause
when the caller is containerised.

**Actual.** Our template set `HttpPutResponseHopLimit: 1`. The deployed worker's first Bedrock
call failed with `NoCredentialsError` in about 2 ms, recorded as having made no network request.
On the same host, everything running outside a container (image pulls, SSM reads during boot)
used the instance role normally, so the role, its policy and IMDS all looked healthy. The cause
is that the Docker bridge adds a network hop, so at a limit of 1 the token response never
reaches a containerised process.

**Impact / severity.** Medium. It blocked the deployed model path until diagnosed, and the
symptom points at IAM or credential configuration rather than at instance metadata options.
Correcting it in place also needed `ec2:ModifyInstanceMetadataOptions`, which the deployment
role did not yet have; a stack update failed and had to be recovered with
`continue-update-rollback` before the fix could land.

**Workaround.** Set `HttpPutResponseHopLimit: 2`, which is what AWS documents for containers on
EC2, while keeping `HttpTokens: required`. Rebooted so every container re-resolved credentials.
The next deployed call returned `semantic.answered` from Bedrock in 1487 ms.

**Actionable suggestion.**
- In the SDKs' credential chain, when the IMDSv2 token request gets no response, raise or log a
  specific message ("IMDS token request received no response; if running in a container, check
  the instance's `HttpPutResponseHopLimit`") instead of the generic `NoCredentialsError`.
- In the EC2 console and in `describe-instances` guidance, flag a hop limit of 1 on instances
  that run container runtimes, or surface this in Amazon Q / EC2 instance diagnostics.

**Evidence.**
- [p6.2-first-deployment.md §3.5, row 10](p6.2-first-deployment.md) — the symptom and cause.
- [p6.2-first-deployment.md §7 and §7.1](p6.2-first-deployment.md) — the denied in-place
  modification, the rollback recovery, and the first successful deployed Bedrock call.
- [`deploy/cloudformation/promisepatch.yaml`](../deploy/cloudformation/promisepatch.yaml),
  `MetadataOptions` — the committed setting and its comment.
- Commit `054cafb` (`fix(deploy): let containers reach the instance metadata service`).

---

## 2. A change set reports `Replacement: Conditional` for an EC2 `UserData` edit, which a conservative release guard cannot resolve on its own

**Task.** Ship a template change that edits `Host.UserData` on a running single-host stack,
without risking replacement of the instance (which would re-seed the demo data, drop the TLS
certificate and lose operator state on the host).

**Friction.** The change set is the tool we used to ask "will this destroy my instance?", and for
`UserData` it answered "conditionally", without saying which condition applied to this instance.

**Expected.** A change set whose answer depends on a documented runtime condition says which
condition applies to the resource being updated, so tooling can decide without a separate
documentation lookup.

**Actual.** Every change set that touched `UserData` returned:

```
Modify  AWS::EC2::EIPAssociation  ElasticIpAssociation  Replacement: Conditional
Modify  AWS::EC2::Instance        Host                  Replacement: Conditional
          UserData    RequiresRecreation: Conditionally (DirectModification)
```

Each time we let one execute, it resolved to an in-place stop/start: same instance id, same root
volume, launch time moved. `AdditionalInfo` behaved the same way. The only change we found that
CloudFormation reports as an unconditional replacement is renaming the resource's logical ID.
The `AWS::EC2::Instance` property reference does document `UserData` updates as an interruption
(stop/start) for EBS-backed instances, which matches what we saw; the change set itself did not
connect its `Conditional` to that documented behaviour for this instance. Our guard reads only
the change set, so it treats `Conditional` as `True`, and a `UserData` edit cannot pass through
our ordinary release; it can only be applied after explicitly authorising the host's possible
replacement, even though replacement has not once occurred. We did not adopt a CloudFormation
stack policy denying `Update:Replace` on the host, which AWS provides for this kind of
protection; that is our choice, not a missing AWS feature.

A second, related gap: our first guard matched `Replacement: True` only, and would have executed
a plan AWS had just marked `Conditional`. That was our defect, fixed in our script, but the
three-valued field is easy to read as a boolean.

**Impact / severity.** Medium. Nothing was lost, but under our guard every template change to the
host became a decision to accept possible replacement of a stateful instance. The deployed stack's recorded
template now lags the repository, and later releases had to be carried by a parameter-only
change set as a documented one-off.

**Workaround.**
- The release guard counts `Conditional` as a replacement and deletes the change set unexecuted.
- A release that changes only the image tag is a parameter-only change set against the previous
  template (`--use-previous-template`, every other parameter `UsePreviousValue=true`), executed
  only after confirming `Changes: []`.
- Behaviour a release must change is read at every boot from SSM by a converge script, so
  `UserData` (which cloud-init runs once per instance) rarely needs to move.

**Actionable suggestion.**
- Clearer diagnostics: where a change set reports `Conditional`, include the condition that
  applies (for example, "EBS-backed instance: update requires stop/start, no replacement") when
  the service can determine it for the resource being updated.
- Better linkage: point a `Conditional` result at the property reference entry that documents
  the runtime behaviour for that resource type and property.
- Easier discoverability for conservative release tooling: surface stack-policy protection
  against `Update:Replace` alongside change-set replacement results, so a guard that sees
  `Conditional` can find the existing mechanism.

**Evidence.**
- [non-destructive-release.md §9.3](non-destructive-release.md) — the first live `Conditional`
  and the boolean-guard defect.
- [non-destructive-release.md §10.1, §11.3 and §11.4](non-destructive-release.md) — why the
  stack cannot take the template through a release, the full plan, and the in-place result.
- [p7.3-deployed-judge-surface.md §3.2](p7.3-deployed-judge-surface.md) — `UserData` and
  `AdditionalInfo` both observed as in-place; logical rename as the only unconditional
  replacement.
- [customer-disclosure-hardening.md](customer-disclosure-hardening.md) and
  [bridge-release.md](bridge-release.md), step 4 — the parameter-only change set used for the
  final release, `Changes: []`.

---

## 3. Verifying our narrowly scoped deployment role before deploying needed service-specific probes

**Task.** Before creating any resource, prove that a narrowly scoped deployment role can do
exactly what the stack needs, and that the runtime role may invoke exactly one Bedrock inference
profile.

**Friction.** For our narrowly scoped deployment role, validating all required permissions across
IAM, Bedrock and ECR required service-specific probes, because the role lacked a practical
self-service read-only path. Proving a permission without exercising it depended on per-service
error-code semantics rather than on a single diagnostic.

**Expected.** One read-only way to ask "may this principal perform this action on this resource
ARN?", available to the principal being checked, with consistent denial signalling.

**Actual.**
- `iam:SimulatePrincipalPolicy`, the API intended for this, was itself denied to the role, as
  were `iam:GetRole` and `iam:ListRolePolicies`, so the role could not inspect its own policy.
  The preflight had to be behavioural.
- We found no read-only check for `bedrock:InvokeModel`. We sent a deliberately invalid body
  (`{}`) and read the error class: `AccessDeniedException` means denied, `ValidationException`
  means authorised and then rejected for shape. The control-plane `bedrock:GetFoundationModel`
  is scoped separately and was denied, so it cannot stand in as a proxy.
- Listing APIs authorise against `*`. `ecr:DescribeRepositories` without a repository name was
  denied to a role correctly scoped to `repository/promisepatch/*`, which our first probe
  misreported as a blocker. Naming the repository works, and because authorisation is evaluated
  before existence, `RepositoryNotFoundException` means allowed.
- Denials arrive as `AccessDenied`, `AccessDeniedException` or `UnauthorizedOperation` depending
  on the service, and App Runner answered `SubscriptionRequiredException`, so a preflight needs a
  per-service table of which codes mean "denied" and which mean "authorised but absent".

**Impact / severity.** Low to medium. No deployment was blocked by it, but building a trustworthy
zero-mutation preflight took several iterations, and one false negative was reported before the
probe was corrected. Twelve mutating permissions could not be tested at all and were verified by
hand against their resource ARNs.

**Workaround.** A read-only preflight script that aborts on any API not on its allowlist, probes
resource-scoped reads by exact ARN, keeps "authorised but absent" codes disjoint from denial
codes, and uses the malformed-body probe for Bedrock. After the account owner granted
`iam:SimulatePrincipalPolicy`, it became available for future checks. The runtime policy names
the inference-profile ARN plus the foundation-model ARN in each of the three US Regions the
profile may route to.

**Actionable suggestion.**
- Allow a principal to simulate its own permissions (a self-scoped `SimulatePrincipalPolicy`, or
  an IAM "can I?" API) without granting broad IAM read.
- Add a dry-run mode to `bedrock:InvokeModel` / `Converse`, comparable to EC2's `DryRun`, that
  returns only the authorisation decision.
- Publish, per service, which error codes indicate an authorisation denial versus an
  authorised-but-missing resource, or normalise them in the SDKs.

**Evidence.**
- [p6.1-deployment-preflight.md §1.1](p6.1-deployment-preflight.md) — the denial table, the
  denied self-inspection, the Bedrock probe and the inference-profile scoping.
- [p6.1-deployment-preflight.md §1.2 and §1.5](p6.1-deployment-preflight.md) — the ECR false
  negative and the corrected probe proving both directions against the live account.
- [`scripts/aws_preflight.py`](../scripts/aws_preflight.py) — the read-only preflight.
- [`deploy/cloudformation/promisepatch.yaml`](../deploy/cloudformation/promisepatch.yaml),
  `InvokeExactlyOneModel` — the inference-profile and foundation-model ARNs.

---

## Considered and not included

- **SSM Session Manager non-interactive commands.** `AWS-StartNonInteractiveCommand` does not run
  its `command` through a shell, so pipes and `&&` are passed as literal arguments, and a large
  payload on Windows failed with a misleading "plugin not found" message. Real, but the committed
  record shows only the workaround (`bash -c` with a base64 payload, in
  [hostrun.sh](rehearsals/runs/bridge-release-20261002-740a062838e0/tools/hostrun.sh)), not the
  failures themselves.
- **SSM standard-tier 4 KB parameter limit** for the compose file. A documented limit with an
  advanced tier available; it constrained us, but it is not a developer-experience defect.
- **Latest-AMI resolution turning a release into a replacement.** Our script resolved the latest
  AMI on every run; that is our defect.
- **`logs:StartQuery` and `ecr:DescribeImages` denied.** Choices in our own least-privilege
  policy.
- **Git Bash path rewriting of `/promisepatch/...` SSM names, AWS CLI TLS failures behind a local
  antivirus proxy, and three smoke checks timing out from the workstation.** Workstation issues,
  not AWS behaviour.

## Summary

| Entry | AWS surface | Severity | Workaround |
|---|---|---|---|
| 1. `NoCredentialsError` from containers at hop limit 1 | EC2 IMDSv2, AWS SDK credential chain | Medium | Hop limit 2, `HttpTokens: required` kept, reboot |
| 2. `Replacement: Conditional` on `UserData`, unresolved for our guard | CloudFormation change sets, EC2 | Medium | Treat `Conditional` as replacement; parameter-only change set with `Changes: []`; read config from SSM at boot |
| 3. Our scoped role needed service-specific permission probes | IAM, Bedrock, ECR | Low–medium | Allowlisted read-only preflight; error-class probes; exact-ARN reads |

This log is feedback from building on AWS, not a claim that AWS blocked the project: each issue
had a workaround, and the deployment shipped.

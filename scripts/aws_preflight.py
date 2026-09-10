"""Ask AWS what this identity may already do, and change nothing while asking.

P6 deploys the existing MCP / conversation / recovery path onto AWS. Before any of that, one
question has to be answered honestly: **does the credential in this shell actually have the
permissions the deployment needs?** A deploy that discovers the answer halfway through leaves a
half-built stack and an unclear bill, which is exactly the "hidden deployment blocker" the
roadmap's risk register names.

So this is a *preflight*, and it is read-only by construction rather than by promise:

* Every requirement names the AWS API behind it, and a requirement that carries a probe must
  name an API listed in :data:`READ_ONLY_APIS`. One that does not raises :class:`MutatingProbeError`
  and the run aborts -- the script cannot grow a resource-creating call without that frozen
  list changing first, in a diff a reviewer sees.
* The one apparent exception is deliberate and is not one. ``bedrock:InvokeModel`` has no
  read-only counterpart, so the only way to learn whether this identity may invoke the model is
  to try. The probe sends a body that cannot possibly be valid (``{}``) and reads the *error
  class*: ``AccessDeniedException`` means no, ``ValidationException`` means yes -- authorization
  passed and the request was then rejected for its shape. No inference runs, no tokens are
  consumed, nothing is billed.

**What this can and cannot prove.** It proves read access per service, and it proves the one
runtime model permission. It cannot prove a mutating permission without mutating, and
``iam:SimulatePrincipalPolicy`` -- the API that exists precisely to answer this without side
effects -- is itself denied to this role. Mutating requirements are therefore *declared* here,
with the resource they act on and the reason they are needed, and are reported as ``DECLARED``
rather than tested. When a service's read probe is denied the role has no access to that service
at all, and every declared action against it is blocked with it; that inference is the useful
signal and it is stated as an inference, not as a test result.

Run it::

    uv run python scripts/aws_preflight.py

Exit 0 means every tested requirement is allowed. Exit 2 means at least one is not, and the
table says which. Nothing in the account is modified either way.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

# The role P6 is expected to run as. Anything else -- an IAM user, a differently named role,
# and above all the account root -- is refused rather than probed, because a preflight that
# passed as root would say nothing about whether the deployment role can deploy.
EXPECTED_ROLE_NAME = "PromisePatchDeveloperRole"

# The exact model the orchestrator uses: a US cross-region inference profile, not a bare
# foundation model. The distinction is load-bearing, because a policy scoped to the
# foundation-model ARN alone does not authorize the profile, or the reverse.
BEDROCK_INFERENCE_PROFILE = "us.amazon.nova-2-lite-v1:0"
BEDROCK_FOUNDATION_MODEL = "amazon.nova-2-lite-v1:0"

DEFAULT_REGION = "us-east-1"

DENIAL_CODES = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"})
UNAVAILABLE_CODES = frozenset({"SubscriptionRequiredException", "OptInRequired"})

# Frozen. Every API a probe in this file is allowed to call, and every one of them is a read.
# ``bedrock:InvokeModel`` is listed for the reason given in the module docstring: the probe
# deliberately fails validation before any inference can happen.
READ_ONLY_APIS = frozenset(
    {
        "bedrock:GetFoundationModel",
        "bedrock:InvokeModel",
        "cloudformation:ListStacks",
        "ec2:DescribeVpcs",
        "ecr:DescribeRepositories",
        "iam:ListRoles",
        "iam:SimulatePrincipalPolicy",
        "logs:DescribeLogGroups",
        "rds:DescribeDBInstances",
        "ssm:DescribeParameters",
        "sts:GetCallerIdentity",
    }
)


class MutatingProbeError(RuntimeError):
    """A requirement carries a probe but does not name an API in :data:`READ_ONLY_APIS`."""


class Plane(Enum):
    """Which side of the deployment a permission lives on.

    The split drives the policy ask. A ``DEPLOYMENT`` permission is held by a person or by a
    CloudFormation service role and can be revoked once the stack exists; a ``RUNTIME``
    permission is held by the instance profile for as long as the deployment runs. Granting a
    runtime permission to the deploying principal, or the reverse, is how blast radius grows
    quietly.
    """

    PREFLIGHT = "preflight"
    DEPLOYMENT = "deployment"
    RUNTIME = "runtime"


class Verdict(Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    DECLARED = "DECLARED"


Probe = Callable[[boto3.Session, str, str], None]


@dataclass(frozen=True)
class Requirement:
    """One AWS permission the deployment needs, and how -- or whether -- it can be tested."""

    api: str
    resource: str
    why: str
    plane: Plane
    probe: Probe | None = None
    # Informational requirements are probed and reported but never block a deployment: they
    # describe the account rather than gate it. ``iam:SimulatePrincipalPolicy`` would only have
    # made this script more capable, and ``bedrock:GetFoundationModel`` is a control-plane read
    # the running system never performs. Neither absence stops anything.
    required: bool = True

    @property
    def tested(self) -> bool:
        return self.probe is not None

    @property
    def probed_api(self) -> str:
        """The single API a probe would call: the first, before any additional actions."""
        return self.api.split(",")[0].strip()


@dataclass(frozen=True)
class Result:
    requirement: Requirement
    verdict: Verdict
    detail: str = ""


@dataclass
class Preflight:
    """The outcome of one preflight: an identity, and a verdict per requirement."""

    identity: dict[str, str] = field(default_factory=dict)
    results: list[Result] = field(default_factory=list)

    @property
    def blocked(self) -> list[Result]:
        return [
            r
            for r in self.results
            if r.requirement.required and r.verdict in (Verdict.DENIED, Verdict.UNAVAILABLE)
        ]

    @property
    def tested(self) -> list[Result]:
        return [r for r in self.results if r.verdict is not Verdict.DECLARED]

    @property
    def allowed(self) -> list[Result]:
        return [r for r in self.results if r.verdict is Verdict.ALLOWED]

    @property
    def declared(self) -> list[Result]:
        return [r for r in self.results if r.verdict is Verdict.DECLARED]


def _client(session: boto3.Session, service: str, region: str) -> Any:
    # Short timeouts and no retries: a preflight that hangs for a minute on a denied call is a
    # preflight nobody runs, and a retried AccessDenied is still an AccessDenied.
    return session.client(
        service,
        region_name=region,
        config=Config(retries={"max_attempts": 1}, connect_timeout=8, read_timeout=15),
    )


def _probe_sts(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "sts", region).get_caller_identity()


def _probe_simulate(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "iam", region).simulate_principal_policy(
        PolicySourceArn=f"arn:aws:iam::{account}:role/{EXPECTED_ROLE_NAME}",
        ActionNames=["ec2:RunInstances"],
    )


def _probe_iam_read(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "iam", region).list_roles(MaxItems=5)


def _probe_cloudformation(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "cloudformation", region).list_stacks()


def _probe_ec2(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "ec2", region).describe_vpcs(MaxResults=5)


def _probe_ecr(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "ecr", region).describe_repositories(maxResults=5)


def _probe_rds(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "rds", region).describe_db_instances(MaxRecords=20)


def _probe_ssm(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "ssm", region).describe_parameters(MaxResults=5)


def _probe_logs(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "logs", region).describe_log_groups(limit=5)


def _probe_bedrock_control(session: boto3.Session, region: str, account: str) -> None:
    _client(session, "bedrock", region).get_foundation_model(
        modelIdentifier=BEDROCK_FOUNDATION_MODEL
    )


def _probe_bedrock_invoke(session: boto3.Session, region: str, account: str) -> None:
    """Authorization-only probe: no inference, no tokens, no charge.

    A ``ValidationException`` is the *success* signal and is swallowed here, because it can only
    be reached once the authorization check has already passed. Every other error propagates and
    is classified normally.
    """
    try:
        _client(session, "bedrock-runtime", region).invoke_model(
            modelId=BEDROCK_INFERENCE_PROFILE, body=b"{}"
        )
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) == "ValidationException":
            return
        raise


def requirements() -> tuple[Requirement, ...]:
    """Every permission the P6 deployment needs, tested wherever a read-only test exists."""
    return (
        Requirement(
            api="sts:GetCallerIdentity",
            resource="*",
            why="establish which identity the rest of this table describes",
            plane=Plane.PREFLIGHT,
            probe=_probe_sts,
        ),
        Requirement(
            api="iam:SimulatePrincipalPolicy",
            resource=f"role/{EXPECTED_ROLE_NAME}",
            why="the only API that could prove a mutating permission without mutating",
            plane=Plane.PREFLIGHT,
            probe=_probe_simulate,
            required=False,
        ),
        Requirement(
            api="bedrock:GetFoundationModel",
            resource=f"foundation-model/{BEDROCK_FOUNDATION_MODEL}",
            why="not needed to deploy; probed to show the control plane is separately scoped",
            plane=Plane.PREFLIGHT,
            probe=_probe_bedrock_control,
            required=False,
        ),
        Requirement(
            api="cloudformation:ListStacks, DescribeStacks, CreateChangeSet, ExecuteChangeSet",
            resource="stack/promisepatch-*/*",
            why="the stack is the deployment unit; nothing can be created or read without it",
            plane=Plane.DEPLOYMENT,
            probe=_probe_cloudformation,
        ),
        Requirement(
            api="iam:ListRoles, GetRole, CreateRole, PutRolePolicy, CreateInstanceProfile",
            resource="role/PromisePatch*, instance-profile/PromisePatch*",
            why="create the instance's runtime role; no other principal is created anywhere",
            plane=Plane.DEPLOYMENT,
            probe=_probe_iam_read,
        ),
        Requirement(
            api="iam:PassRole",
            resource="role/PromisePatchInstanceRole, PassedToService ec2.amazonaws.com",
            why="attach that one role to that one instance, and nothing else anywhere",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="ec2:DescribeVpcs, DescribeSubnets, DescribeSecurityGroups, DescribeImages",
            resource="*",
            why="place the host and the database subnet group in the account's existing VPC",
            plane=Plane.DEPLOYMENT,
            probe=_probe_ec2,
        ),
        Requirement(
            api="ec2:RunInstances, TerminateInstances, StopInstances, StartInstances",
            resource="instance/* created by this stack",
            why="the single host that runs api, worker, mcp, the simulator and the TLS proxy",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="ec2:CreateSecurityGroup, AuthorizeSecurityGroupIngress, "
            "AuthorizeSecurityGroupEgress",
            resource="security-group/* in the stack's VPC",
            why="inbound 80/443 only; egress 443 plus the database port and nothing else",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="ec2:AllocateAddress, AssociateAddress, ReleaseAddress",
            resource="elastic-ip/* created by this stack",
            why="a stable address, so the TLS hostname survives an instance stop and start",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="ecr:DescribeRepositories, CreateRepository, PutLifecyclePolicy",
            resource="repository/promisepatch/*",
            why="the three image repositories the host pulls from",
            plane=Plane.DEPLOYMENT,
            probe=_probe_ecr,
        ),
        Requirement(
            api="ecr:GetAuthorizationToken, InitiateLayerUpload, UploadLayerPart, "
            "CompleteLayerUpload, PutImage",
            resource="repository/promisepatch/{backend,order-simulator,frontend}",
            why="push the locally built images; an image push is not a CloudFormation action",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="rds:DescribeDBInstances, DescribeDBSubnetGroups, DescribeDBEngineVersions",
            resource="db:promisepatch-*, subgrp:promisepatch-*",
            why="the durable PostgreSQL the case state and the step ledger live in",
            plane=Plane.DEPLOYMENT,
            probe=_probe_rds,
        ),
        Requirement(
            api="rds:CreateDBInstance, CreateDBSubnetGroup, ModifyDBInstance, DeleteDBInstance",
            resource="db:promisepatch-*, subgrp:promisepatch-*",
            why="create it private, encrypted, and reachable only from the host's group",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="ssm:DescribeParameters",
            resource="parameter/promisepatch/*",
            why="the secret store; a read proves whether the service is reachable at all",
            plane=Plane.DEPLOYMENT,
            probe=_probe_ssm,
        ),
        Requirement(
            api="ssm:PutParameter, DeleteParameter",
            resource="parameter/promisepatch/*",
            why="write the bearer token, session secret, webhook secret and database password",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="logs:DescribeLogGroups",
            resource="log-group:/promisepatch/*",
            why="where container output goes; a read proves whether the service is reachable",
            plane=Plane.DEPLOYMENT,
            probe=_probe_logs,
        ),
        Requirement(
            api="logs:CreateLogGroup, PutRetentionPolicy, FilterLogEvents",
            resource="log-group:/promisepatch/*",
            why="create the group with a retention limit, and read the deployed loop back out",
            plane=Plane.DEPLOYMENT,
        ),
        Requirement(
            api="bedrock:InvokeModel",
            resource=f"inference-profile/{BEDROCK_INFERENCE_PROFILE}",
            why="the orchestrator's one semantic call; the instance role needs exactly this",
            plane=Plane.RUNTIME,
            probe=_probe_bedrock_invoke,
        ),
        Requirement(
            api="ecr:GetAuthorizationToken, BatchGetImage, GetDownloadUrlForLayer, "
            "BatchCheckLayerAvailability",
            resource="repository/promisepatch/*",
            why="the host pulls its own images at boot and again after a restart",
            plane=Plane.RUNTIME,
        ),
        Requirement(
            api="ssm:GetParameter, GetParameters, GetParametersByPath, kms:Decrypt",
            resource="parameter/promisepatch/*, alias/aws/ssm",
            why="the host reads its secrets at boot; none are baked into an image or an AMI",
            plane=Plane.RUNTIME,
        ),
        Requirement(
            api="logs:CreateLogStream, PutLogEvents, DescribeLogStreams",
            resource="log-group:/promisepatch/*",
            why="container output leaves the host, so a restart cannot erase the evidence",
            plane=Plane.RUNTIME,
        ),
        Requirement(
            api="ssmmessages:*, ec2messages:*",
            resource="*",
            why="Session Manager access, so the host needs no inbound SSH and no key pair",
            plane=Plane.RUNTIME,
        ),
    )


def classify(error: Exception) -> tuple[Verdict, str] | None:
    """Map a botocore failure onto a verdict, or ``None`` if it is not an answer about access."""
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in DENIAL_CODES:
            return (Verdict.DENIED, code)
        if code in UNAVAILABLE_CODES:
            return (Verdict.UNAVAILABLE, code)
        return (Verdict.ERROR, code or type(error).__name__)
    if isinstance(error, BotoCoreError):
        return (Verdict.ERROR, type(error).__name__)
    return None


def run(
    session: boto3.Session,
    region: str,
    account: str,
    required: Sequence[Requirement] | None = None,
) -> Preflight:
    """Probe every testable requirement once. Never calls anything outside the frozen list."""
    preflight = Preflight()
    for requirement in requirements() if required is None else required:
        if requirement.probe is None:
            preflight.results.append(
                Result(requirement=requirement, verdict=Verdict.DECLARED, detail="not testable")
            )
            continue
        if requirement.probed_api not in READ_ONLY_APIS:
            raise MutatingProbeError(
                f"{requirement.probed_api} carries a probe but is not a declared read"
            )
        try:
            requirement.probe(session, region, account)
        except Exception as error:
            classified = classify(error)
            if classified is None:
                raise
            verdict, detail = classified
            preflight.results.append(
                Result(requirement=requirement, verdict=verdict, detail=detail)
            )
        else:
            preflight.results.append(Result(requirement=requirement, verdict=Verdict.ALLOWED))
    return preflight


def _rows(preflight: Preflight) -> Iterator[str]:
    for plane in Plane:
        rows = [r for r in preflight.results if r.requirement.plane is plane]
        if not rows:
            continue
        yield ""
        yield f"-- {plane.value} " + "-" * max(0, 74 - len(plane.value))
        for result in rows:
            detail = f"  ({result.detail})" if result.detail else ""
            if not result.requirement.required:
                detail += "  [informational]"
            yield f"  {result.verdict.value:<11} {result.requirement.api}{detail}"
            yield f"  {'':<11}   on {result.requirement.resource}"
            yield f"  {'':<11}   {result.requirement.why}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zero-mutation AWS deployment preflight.")
    parser.add_argument(
        "--region", default=os.environ.get("PP_AWS_REGION", DEFAULT_REGION), help="AWS region"
    )
    parser.add_argument(
        "--allow-any-identity",
        action="store_true",
        help=f"do not require the caller to be {EXPECTED_ROLE_NAME}",
    )
    arguments = parser.parse_args(argv)

    session = boto3.Session()
    try:
        identity = session.client("sts", region_name=arguments.region).get_caller_identity()
    except (ClientError, BotoCoreError, NoCredentialsError) as error:
        print(f"cannot establish caller identity: {error}", file=sys.stderr)
        return 2

    arn = str(identity["Arn"])
    account = str(identity["Account"])
    print(f"identity : {arn}")
    print(f"account  : {account}")
    print(f"region   : {arguments.region}")

    if ":root" in arn:
        print("\nREFUSED: this is the account root. Assume the developer role.", file=sys.stderr)
        return 2
    if EXPECTED_ROLE_NAME not in arn and not arguments.allow_any_identity:
        print(
            f"\nREFUSED: expected {EXPECTED_ROLE_NAME}; pass --allow-any-identity to override.",
            file=sys.stderr,
        )
        return 2

    preflight = run(session, arguments.region, account)
    preflight.identity = {k: str(v) for k, v in identity.items() if k != "ResponseMetadata"}
    for line in _rows(preflight):
        print(line)

    print()
    required_tested = [r for r in preflight.tested if r.requirement.required]
    required_allowed = [r for r in required_tested if r.verdict is Verdict.ALLOWED]
    print(f"tested   : {len(required_allowed)}/{len(required_tested)} required allowed")
    print(f"declared : {len(preflight.declared)} mutating requirements, not testable read-only")

    if preflight.blocked:
        print("\nBLOCKED. The deployment cannot proceed with this identity:")
        for result in preflight.blocked:
            print(f"  - {result.requirement.probed_api} ({result.detail})")
        print("\nThe exact policy this needs: docs/p6.1-deployment-preflight.md")
        return 2

    print("\nEvery tested requirement is allowed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

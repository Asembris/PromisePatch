"""The deployment definition, and the properties it is not allowed to lose.

No AWS call happens here -- the directory's socket guard would refuse one -- and no deployment
exists yet. What these tests hold is the part of a deployment that can be wrong on disk, before
anybody spends money finding out:

* the two files uploaded as SSM parameters still fit a standard-tier parameter;
* every variable the deployed composition interpolates is one the host actually writes;
* nothing in the deployment turns TLS verification off, anywhere, in any form;
* no policy asks for ``AdministratorAccess`` and no ``iam:PassRole`` is wildcarded;
* the database cannot be made publicly accessible by this template;
* the runtime role can invoke exactly one model, by both the names a cross-region inference
  profile needs;
* the preflight cannot grow a mutating call without its frozen read-only list changing;
* the smoke check's pinned protocol revision is still the server's own.

Several of these are the kind of thing that is obviously true the day it is written and quietly
false a month later. That is what makes them worth asserting rather than reviewing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from botocore.exceptions import ClientError
from scripts.aws_preflight import (
    AUTHORIZED_BUT_ABSENT_CODES,
    BEDROCK_FOUNDATION_MODEL,
    BEDROCK_INFERENCE_PROFILE,
    DENIAL_CODES,
    ECR_PROBE_REPOSITORY,
    READ_ONLY_APIS,
    MutatingProbeError,
    Plane,
    Requirement,
    Result,
    Verdict,
    _probe_ecr,
    requirements,
    run,
)
from scripts.deployment_smoke import PROTOCOL_REVISION

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY = REPOSITORY_ROOT / "deploy"
TEMPLATE_PATH = DEPLOY / "cloudformation" / "promisepatch.yaml"
COMPOSE_PATH = DEPLOY / "compose" / "docker-compose.deploy.yml"
CADDYFILE_PATH = DEPLOY / "compose" / "Caddyfile"
POLICY_PATHS = tuple(sorted((DEPLOY / "policies").glob("*.json")))

# A standard-tier SSM parameter. Advanced tier would hold 8192 bytes and cost money per
# parameter per month; the composition has no business being that big.
SSM_STANDARD_TIER_LIMIT = 4096

# Every spelling of "trust whatever certificate turns up" that could plausibly appear in a
# shell script, a Python client, a compose file or a proxy configuration.
TLS_BYPASSES = (
    "verify=False",
    "verify = False",
    "--insecure",
    "--no-verify-ssl",
    "InsecureSkipVerify",
    "tls_insecure",
    "tls_skip_verify",
    "NODE_TLS_REJECT_UNAUTHORIZED",
    "PYTHONHTTPSVERIFY",
    "CURL_CA_BUNDLE=",
    "ssl._create_unverified_context",
    "check_hostname = False",
    "CERT_NONE",
)


class CloudFormationLoader(yaml.SafeLoader):
    """Reads short-form intrinsics as data, so the template can be inspected without deploying.

    ``!Sub`` and friends are tags PyYAML has never heard of. Turning each into a one-key
    mapping keeps the structure inspectable and keeps the assertions below honest: they are
    reading the template CloudFormation would receive, not a reformatted copy of it.
    """


def _intrinsic(loader: yaml.Loader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    if isinstance(node, yaml.MappingNode):
        return {suffix: loader.construct_mapping(node, deep=True)}
    raise TypeError(f"unexpected node behind !{suffix}: {type(node).__name__}")


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    loaded = yaml.load(TEMPLATE_PATH.read_text(encoding="utf-8"), Loader=CloudFormationLoader)
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def policies() -> dict[str, dict[str, Any]]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in POLICY_PATHS}


def _statements(policy: dict[str, Any]) -> list[dict[str, Any]]:
    statements = policy.get("Statement", [])
    assert isinstance(statements, list)
    return statements


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _deploy_text() -> dict[Path, str]:
    """Every deployment file, plus the two scripts that talk to a deployed endpoint.

    Comment lines are stripped first. A disabled-verification flag inside a comment does
    nothing, and a scanner that failed on one would force the documentation to stop naming the
    thing it forbids -- which is how a rule becomes folklore.
    """
    paths = [p for p in DEPLOY.rglob("*") if p.is_file()]
    paths += [
        REPOSITORY_ROOT / "scripts" / "deployment_smoke.py",
        REPOSITORY_ROOT / "scripts" / "aws_preflight.py",
    ]
    return {p: _without_comments(p.read_text(encoding="utf-8")) for p in paths}


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(("#", "*", "//"))
    )


# ------------------------------------------------------------------ what the host can receive


def test_uploaded_files_fit_a_standard_tier_parameter() -> None:
    for path in (COMPOSE_PATH, CADDYFILE_PATH):
        size = len(path.read_bytes())
        assert size <= SSM_STANDARD_TIER_LIMIT, (
            f"{path.name} is {size} bytes; a standard-tier SSM parameter holds "
            f"{SSM_STANDARD_TIER_LIMIT}. Shorten it rather than paying for advanced tier."
        )


def test_every_interpolated_variable_is_one_the_host_writes(template: dict[str, Any]) -> None:
    """A composition referring to a variable nobody sets would start with empty image names."""
    user_data = _user_data(template)
    referenced = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", COMPOSE_PATH.read_text("utf-8")))
    assert referenced, "the composition interpolates nothing, which cannot be right"
    for name in sorted(referenced):
        # The host writes these into env/stack.env, which `docker compose --env-file` reads.
        assert f"{name}=" in user_data, (
            f"the composition interpolates ${{{name}}} but the host never writes it; "
            "docker compose would substitute an empty string"
        )


def test_the_composition_runs_the_same_processes_as_the_local_stack(
    compose: dict[str, Any],
) -> None:
    services = set(compose["services"])
    # `postgres` is deliberately absent: the deployed database is RDS. `frontend` is
    # deliberately absent: it is a Vite dev server and needs a static build stage first.
    assert {"migrate", "seed", "api", "worker", "mcp", "order-simulator"} <= services
    assert "postgres" not in services
    assert "caddy" in services, "something has to terminate TLS"


def test_the_mcp_container_is_given_no_database_url(template: dict[str, Any]) -> None:
    """The authority boundary is which environment file each container receives.

    ``mcp`` reaches a case only by an authenticated call to ``api``. If a deployment handed it a
    connection string, the import-linter contract would still forbid the import -- but the
    credential would be sitting in the process, one careless commit away from being used.
    """
    mcp_block = _env_file_block(template, "mcp.env", "order-simulator.env")
    assert "PP_DATABASE_URL" not in mcp_block
    assert "PP_MIGRATION_DATABASE_URL" not in mcp_block
    assert "PP_MCP_INTENT_API_BASE_URL" in mcp_block


def test_the_order_simulator_holds_no_postgres_credential(template: dict[str, Any]) -> None:
    block = _env_file_block(template, "order-simulator.env", "stack.env")
    assert "DATABASE_URL" not in block
    assert "OS_WEBHOOK_SECRET" in block, "it still has to sign its events"


def test_every_variable_the_host_writes_is_one_something_actually_reads(
    template: dict[str, Any],
) -> None:
    """A misprefixed variable is silently ignored, which is the worst way for this to fail.

    The order simulator reads ``OS_``-prefixed settings and PromisePatch reads ``PP_``-prefixed
    ones. Writing ``PP_ORDER_SYSTEM_WEBHOOK_URL`` into the simulator's environment file would
    not error: the container would boot with no webhook target at all, and the first sign of it
    would be an external change that never arrived. So each name is checked against the file
    that declares it -- ``.env.example`` for PromisePatch, whose agreement with the
    implementation's settings is asserted by the backend suite in both directions, and the
    simulator's own example for the simulator.
    """
    declared_pp = set(
        re.findall(
            r"^(PP_[A-Z0-9_]+)=", (REPOSITORY_ROOT / ".env.example").read_text("utf-8"), re.M
        )
    )
    declared_os = set(
        re.findall(
            r"^(OS_[A-Z0-9_]+)=",
            (REPOSITORY_ROOT / "docker" / "env" / "order-simulator.env.example").read_text("utf-8"),
            re.M,
        )
    )
    assert declared_pp and declared_os, "neither example file declares anything, which is wrong"

    user_data = json.dumps(template["Resources"]["Host"]["Properties"]["UserData"])
    for name in sorted(set(re.findall(r"\\n\s*((?:PP|OS)_[A-Z0-9_]+)=", user_data))):
        declared = declared_pp if name.startswith("PP_") else declared_os
        assert name in declared, (
            f"the host writes {name}, which no example file declares. A setting nothing reads "
            "is not an error at boot -- it is a container that quietly does nothing."
        )


def _user_data(template: dict[str, Any]) -> str:
    """The host's bootstrap script as text, not as a JSON dump of the node that holds it.

    ``UserData`` is ``!Base64 !Sub <script>``, which the loader turns into nested one-key
    mappings. Reading the scalar out gives the real script with real newlines; searching a
    ``json.dumps`` of it instead is how a line-anchored pattern silently matches nothing.
    """
    node: Any = template["Resources"]["Host"]["Properties"]["UserData"]
    # `Fn::Base64` is spelled long-form in the template and `!Sub` short-form, so the nesting is
    # {"Fn::Base64": {"Sub": <script>}}. Unwrap whatever single-key layers are there rather than
    # hard-coding one spelling of an intrinsic that has two.
    while isinstance(node, dict) and len(node) == 1:
        node = next(iter(node.values()))
    assert isinstance(node, str), f"UserData did not unwrap to a script: {type(node).__name__}"
    assert node.startswith("#!/bin/bash"), "the bootstrap script is not where it was"
    return node


def _env_file_block(template: dict[str, Any], start_marker: str, end_marker: str) -> str:
    script = _user_data(template)
    return script[script.index(start_marker) : script.index(end_marker)]


# ------------------------------------------------------------------------------- TLS and egress


@pytest.mark.parametrize("bypass", TLS_BYPASSES)
def test_nothing_in_the_deployment_disables_tls_verification(bypass: str) -> None:
    for path, text in _deploy_text().items():
        assert bypass not in text, (
            f"{path.relative_to(REPOSITORY_ROOT)} contains {bypass!r}. The deployment exists "
            "partly to prove real TLS; a bypass here would make the proof circular."
        )


def test_the_host_reaches_only_443_and_its_own_database(template: dict[str, Any]) -> None:
    resources = template["Resources"]
    egress = resources["HostSecurityGroup"]["Properties"]["SecurityGroupEgress"]
    assert [rule["ToPort"] for rule in egress] == [443], (
        "egress is a closed list; a default allow-all would make the egress claim untestable"
    )
    to_database = resources["HostEgressToDatabase"]["Properties"]
    assert to_database["ToPort"] == 5432
    assert "DestinationSecurityGroupId" in to_database, "not a CIDR: the group is the boundary"


def test_the_database_is_reachable_only_from_the_host_group(template: dict[str, Any]) -> None:
    resources = template["Resources"]
    ingress = resources["DatabaseIngressFromHost"]["Properties"]
    assert ingress["FromPort"] == ingress["ToPort"] == 5432
    assert "SourceSecurityGroupId" in ingress
    assert "CidrIp" not in ingress, "a CIDR allowance would be a second path to the database"
    assert resources["Database"]["Properties"]["PubliclyAccessible"] is False


def test_the_database_is_encrypted_and_backed_up(template: dict[str, Any]) -> None:
    properties = template["Resources"]["Database"]["Properties"]
    assert properties["StorageEncrypted"] is True
    assert properties["BackupRetentionPeriod"] >= 1
    # The case state is the evidence a deployed loop happened. A mistyped `delete-stack` must
    # not be able to erase it without leaving a snapshot behind.
    assert template["Resources"]["Database"]["DeletionPolicy"] == "Snapshot"


def test_the_host_requires_imdsv2(template: dict[str, Any]) -> None:
    """This host holds a Bedrock permission; a token-less metadata read is how that leaks."""
    options = template["Resources"]["Host"]["Properties"]["MetadataOptions"]
    assert options["HttpTokens"] == "required"
    assert options["HttpPutResponseHopLimit"] == 1


def test_the_host_has_no_inbound_ssh_and_no_key_pair(template: dict[str, Any]) -> None:
    host = template["Resources"]["Host"]["Properties"]
    assert "KeyName" not in host, "access is Session Manager, so there is no key to leak"
    ingress = template["Resources"]["HostSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert sorted(rule["ToPort"] for rule in ingress) == [80, 443]


# ----------------------------------------------------------------------------------------- IAM


def test_no_policy_asks_for_administrator_access(policies: dict[str, dict[str, Any]]) -> None:
    for name, policy in policies.items():
        text = json.dumps(_statements(policy))
        assert "AdministratorAccess" not in text, f"{name} asks for AdministratorAccess"
        assert '"Action": "*"' not in text, f"{name} asks for every action"


# IAM's policy grammar. Anything outside these sets is a `MalformedPolicyDocument`, not an
# ignored annotation, so a file carrying explanatory prose cannot be applied as written.
IAM_TOP_LEVEL_KEYS = frozenset({"Version", "Id", "Statement"})
IAM_STATEMENT_KEYS = frozenset(
    {
        "Sid",
        "Effect",
        "Principal",
        "NotPrincipal",
        "Action",
        "NotAction",
        "Resource",
        "NotResource",
        "Condition",
    }
)


def test_every_policy_is_a_valid_iam_document(policies: dict[str, dict[str, Any]]) -> None:
    """These files exist to be applied verbatim, so they must be applicable verbatim.

    An earlier version carried a top-level ``Comment`` array explaining each statement. It read
    well and it could not be pasted: IAM rejects an unrecognised key rather than ignoring it, so
    the reviewed form of the policy was not the form anyone could apply. The prose moved to
    ``deploy/policies/README.md`` and this test is what keeps it there.
    """
    for name, policy in policies.items():
        unknown_top = set(policy) - IAM_TOP_LEVEL_KEYS
        assert not unknown_top, (
            f"{name} has non-IAM top-level key(s) {sorted(unknown_top)}; IAM would reject the "
            "document. Explanations belong in deploy/policies/README.md."
        )
        assert policy["Version"] == "2012-10-17"
        statements = _statements(policy)
        assert statements, f"{name} has no statements"
        for statement in statements:
            unknown = set(statement) - IAM_STATEMENT_KEYS
            assert not unknown, (
                f"{name}: statement {statement.get('Sid')} has non-IAM key(s) {sorted(unknown)}"
            )
            assert statement.get("Effect") in ("Allow", "Deny")
            if len(statements) > 1:
                # A multi-statement policy needs names to be reviewable. The single-statement
                # trust policy deliberately has none, because the role in AWS has none and this
                # file is asserted below to match it exactly.
                assert "Sid" in statement, "an unnamed statement cannot be discussed in review"


def test_the_committed_trust_policy_is_exactly_the_one_in_aws(
    policies: dict[str, dict[str, Any]],
) -> None:
    """Pinned to the live document, whitespace and all, because that is the claim it makes.

    Verified against `aws iam get-role --role-name PromisePatchDeploymentRole` on 2026-09-10:
    the live `AssumeRolePolicyDocument` compares equal to this file, with no `Sid` and no
    condition. Anything added here -- even something harmless like a statement id -- reintroduces
    the drift this file was corrected to remove.
    """
    assert policies["deployment-role-trust.json"] == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "cloudformation.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


def test_only_the_account_wide_log_query_is_account_wide(
    policies: dict[str, dict[str, Any]],
) -> None:
    """`logs:DescribeLogGroups` needs `*`; nothing that can read a log line is allowed it.

    Scoping `DescribeLogGroups` to `log-group:/promisepatch/*` denies it outright -- it answers
    "which groups exist", a question with no single resource -- which is what the first version
    of this policy did, leaving the deployment unable to find its own log group. It therefore
    gets `*`, alone, in its own statement, so the breadth is visible and bounded. Every action
    that can return log *content* stays scoped.
    """
    delta = policies["developer-role-delta.json"]
    unscoped: set[str] = set()
    scoped: set[str] = set()
    for statement in _statements(delta):
        if statement.get("Effect") != "Allow":
            continue
        every = (str(x) for x in _as_list(statement.get("Action")))
        actions = [a for a in every if a.startswith("logs:")]
        if not actions:
            continue
        resources = [str(r) for r in _as_list(statement.get("Resource"))]
        target = unscoped if "*" in resources else scoped
        target.update(actions)
        if target is scoped:
            for resource in resources:
                assert "log-group:/promisepatch/" in resource, (
                    f"a logs statement is scoped to {resource}, which is not this deployment's"
                )

    assert unscoped == {"logs:DescribeLogGroups"}, (
        f"exactly one logs action may be account-wide; found {sorted(unscoped)}"
    )
    assert scoped >= {"logs:GetLogEvents", "logs:FilterLogEvents", "logs:DescribeLogStreams"}, (
        f"actions that read log content must stay scoped; found {sorted(scoped)}"
    )


def test_no_pass_role_is_wildcarded(policies: dict[str, dict[str, Any]]) -> None:
    """A wildcard ``PassRole`` escalates to whatever the best role in the account happens to be."""
    for name, policy in policies.items():
        for statement in _statements(policy):
            actions = [str(a) for a in _as_list(statement.get("Action"))]
            if not any(a == "iam:PassRole" or a == "iam:*" for a in actions):
                continue
            if statement.get("Effect") == "Deny":
                continue
            resources = [str(r) for r in _as_list(statement.get("Resource"))]
            assert resources, f"{name}: an Allow on iam:PassRole with no Resource"
            for resource in resources:
                assert resource != "*", f"{name}: iam:PassRole on * in {statement.get('Sid')}"
                assert "role/*" not in resource, f"{name}: iam:PassRole on role/*"
            condition = statement.get("Condition", {})
            passed_to = json.dumps(condition)
            assert "iam:PassedToService" in passed_to, (
                f"{name}: {statement.get('Sid')} passes a role without naming the service it "
                "may be passed to"
            )


def test_the_person_cannot_create_an_iam_principal(policies: dict[str, dict[str, Any]]) -> None:
    """All mutation goes through CloudFormation, so the human role needs no create rights."""
    delta = policies["developer-role-delta.json"]
    denied = {
        action
        for statement in _statements(delta)
        if statement.get("Effect") == "Deny"
        for action in (str(a) for a in _as_list(statement.get("Action")))
    }
    for action in (
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:CreateUser",
        "iam:CreateAccessKey",
        "iam:CreateInstanceProfile",
    ):
        assert action in denied, f"the developer delta does not explicitly deny {action}"


def test_the_deployment_role_can_create_exactly_one_principal(
    policies: dict[str, dict[str, Any]],
) -> None:
    policy = policies["deployment-role-policy.json"]
    creating = [
        statement
        for statement in _statements(policy)
        if statement.get("Effect") == "Allow"
        and "iam:CreateRole" in (str(a) for a in _as_list(statement.get("Action")))
    ]
    assert len(creating) == 1
    assert _as_list(creating[0]["Resource"]) == [
        "arn:aws:iam::ACCOUNT_ID:role/PromisePatchInstanceRole"
    ]


def test_only_cloudformation_can_assume_the_deployment_role(
    policies: dict[str, dict[str, Any]],
) -> None:
    """One service principal, and no way for a person or another account to assume it.

    This trust policy deliberately carries no ``aws:SourceAccount`` or ``aws:SourceArn``
    condition, because the role that exists in AWS carries none. An earlier draft of this file
    did, and a repository that asserted the stricter version would have been asserting something
    untrue about the account. What that condition would have guarded against is guarded instead
    by ``iam:PassRole`` in the developer delta -- see the test below, which is the other half of
    this one and would fail if that control were ever loosened.
    """
    trust = policies["deployment-role-trust.json"]
    (statement,) = _statements(trust)
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRole"
    assert statement["Principal"] == {"Service": "cloudformation.amazonaws.com"}
    assert "Condition" not in statement, (
        "the live role has no trust condition; adding one here would make git disagree with AWS"
    )


def test_the_control_the_trust_policy_does_not_carry_lives_in_pass_role(
    policies: dict[str, dict[str, Any]],
) -> None:
    """The only way the deployment role reaches a stack is for somebody to pass it.

    So restricting *who may pass it where* is the load-bearing control, and it is the reason the
    absent trust condition is a relocation rather than a removal. Both halves are asserted: the
    single narrow ``Allow``, and the ``Deny`` that stops any other role being passed at all.
    """
    delta = policies["developer-role-delta.json"]
    allows = [
        statement
        for statement in _statements(delta)
        if statement.get("Effect") == "Allow"
        and "iam:PassRole" in (str(a) for a in _as_list(statement.get("Action")))
    ]
    (allow,) = allows
    assert _as_list(allow["Resource"]) == [
        "arn:aws:iam::ACCOUNT_ID:role/PromisePatchDeploymentRole"
    ]
    assert allow["Condition"]["StringEquals"]["iam:PassedToService"] == (
        "cloudformation.amazonaws.com"
    )

    denies = [
        statement
        for statement in _statements(delta)
        if statement.get("Effect") == "Deny"
        and "iam:PassRole" in (str(a) for a in _as_list(statement.get("Action")))
    ]
    (deny,) = denies
    assert deny["NotResource"] == "arn:aws:iam::ACCOUNT_ID:role/PromisePatchDeploymentRole"


def test_policies_carry_no_real_account_id(policies: dict[str, dict[str, Any]]) -> None:
    """These files are committed and the repository becomes public at G9."""
    for name, policy in policies.items():
        for account in re.findall(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:(\d{12}):", json.dumps(policy)):
            pytest.fail(f"{name} contains the literal account id {account}; use ACCOUNT_ID")


def test_the_runtime_role_can_invoke_exactly_one_model(template: dict[str, Any]) -> None:
    """And by both names, because a cross-region profile needs the profile and the model."""
    statements = [
        statement
        for policy in template["Resources"]["InstanceRole"]["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if "bedrock:InvokeModel" in (str(a) for a in _as_list(statement.get("Action")))
    ]
    (statement,) = statements
    resources = json.dumps(statement["Resource"])
    assert f"inference-profile/{BEDROCK_INFERENCE_PROFILE}" in resources
    assert f"foundation-model/{BEDROCK_FOUNDATION_MODEL}" in resources
    assert "nova-lite" not in resources.replace("nova-2-lite", ""), "one model, not a family"
    assert '"*"' not in resources


def test_the_runtime_role_reads_only_its_own_secrets(template: dict[str, Any]) -> None:
    statements = [
        statement
        for policy in template["Resources"]["InstanceRole"]["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if any(str(a).startswith("ssm:Get") for a in _as_list(statement.get("Action")))
    ]
    (statement,) = statements
    assert "parameter/promisepatch/" in json.dumps(statement["Resource"])
    assert '"*"' not in json.dumps(statement["Resource"])


# --------------------------------------------------------------------------------- preflight


def test_every_probe_names_a_declared_read() -> None:
    for requirement in requirements():
        if requirement.probe is not None:
            assert requirement.probed_api in READ_ONLY_APIS, (
                f"{requirement.probed_api} carries a probe but is not in READ_ONLY_APIS"
            )


def test_the_frozen_read_list_holds_no_mutating_verb() -> None:
    """``InvokeModel`` is the one documented exception, and it fails validation by design."""
    mutating = re.compile(
        r":(Create|Put|Delete|Run|Modify|Authorize|Revoke|Allocate|Associate|Terminate"
        r"|Start|Stop|Attach|Detach|Update|Add|Remove|Tag|Untag)"
    )
    for api in sorted(READ_ONLY_APIS):
        if api == "bedrock:InvokeModel":
            continue
        assert not mutating.search(api), f"{api} looks like a mutation but is on the read list"


def test_a_probe_on_an_undeclared_api_aborts_the_run() -> None:
    """The guard is the reason this script can be trusted; a guard nobody breaks is untested."""
    smuggled = Requirement(
        api="ec2:RunInstances",
        resource="instance/*",
        why="a probe that would create something",
        plane=Plane.DEPLOYMENT,
        probe=lambda session, region, account: None,
    )
    with pytest.raises(MutatingProbeError, match="ec2:RunInstances"):
        run(session=None, region="us-east-1", account="0", required=[smuggled])


def test_a_declared_requirement_is_reported_rather_than_called() -> None:
    declared = Requirement(
        api="ec2:RunInstances",
        resource="instance/*",
        why="cannot be tested without creating something",
        plane=Plane.DEPLOYMENT,
    )
    preflight = run(session=None, region="us-east-1", account="0", required=[declared])
    (result,) = preflight.results
    assert result.verdict is Verdict.DECLARED
    assert preflight.blocked == []


class _StubEcr:
    """Records how it was called, and answers with whatever error the test wants."""

    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def describe_repositories(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"repositories": []}


class _StubSession:
    def __init__(self, client: Any) -> None:
        self._client = client

    def client(self, service: str, **kwargs: Any) -> Any:
        assert service == "ecr"
        return self._client


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "DescribeRepositories")


def _ecr_result(error: Exception | None) -> tuple[Result, _StubEcr]:
    requirement = next(r for r in requirements() if r.probe is _probe_ecr)
    stub = _StubEcr(error)
    preflight = run(
        session=_StubSession(stub),
        region="us-east-1",
        account="0",
        required=[requirement],
    )
    (result,) = preflight.results
    return result, stub


def test_the_ecr_probe_names_a_repository_rather_than_listing_the_registry() -> None:
    """The listing form asks a question the deployment's own scoping cannot answer.

    ``describe_repositories(maxResults=5)`` is authorized against ``repository/*``, so a role
    scoped to ``repository/promisepatch/*`` -- the scoping this deployment asks for -- is denied
    it while being perfectly able to describe its own repositories. The first version of this
    probe did exactly that and reported a blocker that did not exist.
    """
    _, stub = _ecr_result(None)
    (call,) = stub.calls
    assert call == {"repositoryNames": [ECR_PROBE_REPOSITORY]}
    assert "maxResults" not in call, "a registry listing tests the wrong permission"


def test_a_missing_repository_is_authorization_proved_not_a_blocker() -> None:
    """``RepositoryNotFoundException`` is the expected first-run answer: the repo comes later.

    AWS evaluates authorization before existence, so this code means the call was allowed and
    there was simply nothing to describe -- which is the state before ``deploy.sh registry``
    runs. Reporting it as a denial would block the deployment on its own absence.
    """
    result, _ = _ecr_result(_client_error("RepositoryNotFoundException"))
    assert result.verdict is Verdict.ALLOWED


def test_a_denied_repository_read_is_still_a_blocker() -> None:
    """The distinction is the entire value of the probe, so both sides are asserted."""
    result, _ = _ecr_result(_client_error("AccessDeniedException"))
    assert result.verdict is Verdict.DENIED
    assert result.detail == "AccessDeniedException"


def test_absent_is_never_confused_with_denied() -> None:
    assert not (AUTHORIZED_BUT_ABSENT_CODES & DENIAL_CODES)


def test_the_preflight_declares_both_planes() -> None:
    planes = {requirement.plane for requirement in requirements()}
    assert Plane.DEPLOYMENT in planes and Plane.RUNTIME in planes
    runtime = [r for r in requirements() if r.plane is Plane.RUNTIME]
    assert any(r.probed_api == "bedrock:InvokeModel" for r in runtime)


# -------------------------------------------------------------------------------- smoke check


def test_the_smoke_check_pins_the_servers_own_protocol_revision() -> None:
    """A smoke check that drifted off the pinned revision would pass the wrong surface."""
    server = (
        REPOSITORY_ROOT / "apps" / "backend" / "src" / "promisepatch" / "mcp" / "server.py"
    ).read_text(encoding="utf-8")
    match = re.search(r'PROTOCOL_REVISION:\s*Final\s*=\s*"([0-9-]+)"', server)
    assert match is not None, "the server no longer declares PROTOCOL_REVISION as expected"
    assert match.group(1) == PROTOCOL_REVISION


def test_the_smoke_check_asserts_refusals_and_not_only_availability() -> None:
    """Half these checks exist to fail a deployment that came up too permissive."""
    from scripts.deployment_smoke import CHECKS

    names = {check.__name__ for check in CHECKS}
    assert {
        "check_mcp_requires_bearer",
        "check_origin_refused",
        "check_host_refused",
        "check_webhook_rejects_unsigned",
    } <= names

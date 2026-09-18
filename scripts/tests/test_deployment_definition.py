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
* the ECR probe names a repository instead of listing the registry, and tells "you may, and
  there is nothing there" apart from "you may not";
* exactly one CloudWatch Logs action is account-wide, and it is the one that cannot be scoped;
* every policy file is a document IAM would actually accept, and the deployment role's trust
  policy is the one that exists in AWS rather than a stricter draft of it;
* the smoke check's pinned protocol revision is still the server's own.

Several of these are the kind of thing that is obviously true the day it is written and quietly
false a month later. That is what makes them worth asserting rather than reviewing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import jmespath
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

from promisepatch.config import Settings
from promisepatch.fixtures import demo

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY = REPOSITORY_ROOT / "deploy"
TEMPLATE_PATH = DEPLOY / "cloudformation" / "promisepatch.yaml"
COMPOSE_PATH = DEPLOY / "compose" / "docker-compose.deploy.yml"
CADDYFILE_PATH = DEPLOY / "compose" / "Caddyfile"
BACKEND_DOCKERFILE_PATH = REPOSITORY_ROOT / "docker" / "Dockerfile.backend"

HOST = "Host"
"""The instance's logical name.

Renaming it is how the instance is deliberately replaced: a change to ``UserData`` and a
change to ``AdditionalInfo`` are both reported by a change set as ``Conditionally`` and both
were observed resolving to an in-place modification, while a new logical name is always an
Add and a Remove. It has moved twice and should not move again, now that the host converges
from SSM at every boot. Named here rather than repeated, so the next one is one edit.
"""
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


def test_every_template_reference_in_the_bootstrap_script_resolves(
    template: dict[str, Any],
) -> None:
    """A shell variable the template tries to resolve is a deploy that never starts.

    ``Fn::Sub`` claims every ``${...}`` in the script unless it is escaped, and its escape is
    ``${!NAME}`` -- *not* ``$${NAME}``, which is docker compose's and CodeBuild's. The two look
    alike, the wrong one is silently a template reference, and CloudFormation rejects the whole
    template with ``Unresolved resource dependencies`` before a single resource is created. It
    is only reachable by deploying, so it is asserted here instead.
    """
    node: Any = template["Resources"][HOST]["Properties"]["UserData"]
    while isinstance(node, dict) and len(node) == 1:
        node = next(iter(node.values()))
    script, supplied = node

    assert "$${" not in script, (
        "`$${NAME}` is not a CloudFormation escape. Fn::Sub escapes with `${!NAME}`, and "
        "`$${NAME}` is read as a reference to a resource called NAME."
    )

    resolvable = set(template["Parameters"]) | set(template["Resources"]) | set(supplied)
    for reference in sorted(set(re.findall(r"\$\{([^!}][^}]*)\}", script))):
        root = reference.split(".", 1)[0]
        assert root.startswith("AWS::") or root in resolvable, (
            f"the bootstrap script refers to ${{{reference}}}, which the template cannot "
            "resolve. If it is meant to be a shell variable, escape it as ${!" + reference + "}."
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


def test_a_restart_cannot_reseed_the_database(
    template: dict[str, Any], compose: dict[str, Any]
) -> None:
    """The state is durable, and the boot sequence must not erase it anyway.

    ``pp reset-demo-state`` replaces every domain row PromisePatch owns -- cases included. The
    systemd unit runs ``docker compose up -d`` at every boot, and a one-shot service that has
    already exited is re-run by it, so leaving ``seed`` outside a profile means every host
    restart wipes the very cases the deployment exists to prove outlive the host. It was
    observed doing exactly that: a case reached over the deployed MCP surface was gone after
    one reboot, with the database itself perfectly intact.

    Three things keep it fixed: the service is profiled, nothing pulls it in as a dependency
    (``depends_on`` implicitly enables a dependency's profile), and the bootstrap -- which runs
    once per instance -- is the only thing that starts it.
    """
    seed = compose["services"]["seed"]
    assert "seed" in seed.get("profiles", []), (
        "`seed` is not profiled, so `docker compose up -d` re-runs it at every boot"
    )
    for name, service in compose["services"].items():
        assert "seed" not in (service.get("depends_on") or {}), (
            f"{name} depends on `seed`, which enables its profile again and undoes the fix"
        )
    script = _user_data(template)
    assert "run --rm -T seed" in script, "nothing seeds a new instance at all"
    assert "up -d" in script
    # The seed runs once, in the provisioning script, and is not reachable from the script the
    # systemd unit runs at every boot.
    assert script.index("CONVERGE") < script.index("run --rm -T seed")


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


def test_the_attesting_worker_is_one_the_seed_actually_creates(
    template: dict[str, Any],
) -> None:
    """The worker every statement over the MCP surface is attributed to must exist.

    Intake refuses an unknown attester rather than inventing one, so a name the fixture does
    not seed is not a cosmetic mislabel: it is ``SURFACE_WORKER_MISSING`` on the first spoken
    turn of every conversation, in a deployment where everything else came up healthy.
    """
    seeded = {seed.username for seed in demo.STAFF}
    assert seeded, "the fixture seeds no staff at all, which cannot be right"
    named = set(re.findall(r"^\s*PP_SURFACE_WORKER_ID=(\S+)$", _user_data(template), re.M))
    assert named, "the deployment attributes statements to nobody"
    assert named <= seeded, (
        f"the deployment attests as {sorted(named - seeded)}, which `pp reset-demo-state` "
        f"never creates; it seeds {sorted(seeded)}"
    )


def test_the_deployed_api_is_pointed_at_a_real_model(template: dict[str, Any]) -> None:
    """``llm_provider`` defaults to the fake one, and is deliberately not inferred from ``env``.

    So a deployment that wants a model has to say so. Leaving it unsaid is not a broken
    deployment -- everything comes up and every endpoint answers -- it is a deployment whose
    one semantic call quietly never happens, which is the failure that looks most like success.
    The instance role carries ``bedrock:InvokeModel`` precisely so this line can be true.
    """
    block = _env_file_block(template, "api.env", "mcp.env")
    assert "PP_LLM_PROVIDER=bedrock" in block, (
        "the deployed api would run the fake provider: the loop would work and call no model"
    )
    assert "PP_BEDROCK_MODEL_ID=" in block, "which model is not left to a default here"


def test_the_deployment_offers_the_one_action_way_in_and_the_repository_does_not(
    template: dict[str, Any],
) -> None:
    """A judge reaches a real case in one action here, and nowhere else by default.

    ``POST /api/auth/demo-session`` issues a session naming the seeded observer, which the
    domain admits to case reads and refuses every write. That is a deliberate choice for this
    deployment rather than a standing unauthenticated session endpoint in every copy of the
    repository, so the setting is on in the host's environment file and off in the model's
    default -- and the second half is what this asserts alongside the first.
    """
    block = _env_file_block(template, "api.env", "mcp.env")
    assert "PP_DEMO_SESSION_ENABLED=true" in block, (
        "the deployed API does not serve the observer session, so the judge entry is not there"
    )
    assert Settings.model_fields["demo_session_enabled"].default is False, (
        "the endpoint is on by default, which makes every copy of this repository serve it"
    )


def test_the_deployed_worker_reads_the_setting_that_provisions_the_case(
    compose: dict[str, Any], template: dict[str, Any]
) -> None:
    """The entry and the case a judge lands on cannot be configured apart on the deployed host.

    Provisioning runs at the worker's start rather than in a service of its own -- the composition
    is uploaded to a 4096-byte SSM parameter and has no room for one -- and it is gated on the
    same `PP_DEMO_SESSION_ENABLED` that serves the entry. So the worker must read the file that
    carries it, and no new service may appear to carry it instead.
    """
    assert compose["services"]["worker"]["env_file"] == compose["services"]["api"]["env_file"]
    assert "PP_DEMO_SESSION_ENABLED=true" in _env_file_block(template, "api.env", "mcp.env")


def test_the_deployment_serves_the_page_from_the_image_rather_than_from_configuration(
    template: dict[str, Any],
) -> None:
    """``PP_STATIC_ROOT`` belongs to the image that carries the bundle, not to the host.

    A host that had to be told where the bundle is could be told wrongly, or not at all, and
    the symptom either way is a deployment that answers every API call and shows no page.
    """
    script = _user_data(template)
    assert "PP_STATIC_ROOT" not in script, (
        "the host configures where the bundle is; the image that built it already knows"
    )


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

    user_data = json.dumps(template["Resources"][HOST]["Properties"]["UserData"])
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
    node: Any = template["Resources"][HOST]["Properties"]["UserData"]
    # `Fn::Base64` is spelled long-form in the template and `Fn::Sub` may be either spelling, so
    # unwrap whatever single-key layers are there rather than hard-coding one of them.
    while isinstance(node, dict) and len(node) == 1:
        node = next(iter(node.values()))
    # `Fn::Sub` has two forms: a bare script, and `[script, {name: value}]` when the template
    # supplies a substitution of its own. Both hold the same script in the same place.
    if isinstance(node, list):
        assert len(node) == 2, f"an Fn::Sub list form has two members, not {len(node)}"
        node, supplied = node
        assert isinstance(supplied, dict) and supplied, "the list form supplies nothing"
        for name in supplied:
            assert "${" + name + "}" in node, (
                f"the template supplies ${{{name}}} to the bootstrap script, which never reads "
                "it. A substitution nothing uses is a rename that half happened."
            )
    assert isinstance(node, str), f"UserData did not unwrap to a script: {type(node).__name__}"
    assert node.startswith("#!/bin/bash"), "the bootstrap script is not where it was"
    return node


def _user_data_substitutions(template: dict[str, Any]) -> dict[str, Any]:
    """The substitutions the template supplies to the bootstrap script, by whichever spelling.

    ``Fn::Base64`` and ``Fn::Sub`` each have a long and a short form, so the nesting depends on
    how the template happens to be written. Unwrapping single-key layers reaches the ``Fn::Sub``
    list form without hard-coding one of four spellings.
    """
    node: Any = template["Resources"][HOST]["Properties"]["UserData"]
    while isinstance(node, dict) and len(node) == 1:
        node = next(iter(node.values()))
    assert isinstance(node, list), "the bootstrap script is given no substitutions of its own"
    supplied = node[1]
    assert isinstance(supplied, dict)
    return supplied


def _env_file_block(template: dict[str, Any], start_marker: str, end_marker: str) -> str:
    script = _user_data(template)
    return script[script.index(start_marker) : script.index(end_marker)]


def test_the_image_is_built_knowing_which_commit_it_is() -> None:
    """Otherwise "which version is deployed" is answered by asserting it rather than asking.

    ``deploy.sh`` refuses to tag a dirty tree, so the tag names a commit; baking it in means the
    running process can say so, and the smoke check can compare that with the tag the stack
    declares. Without the build argument the image is anonymous and the comparison is impossible
    -- which is the state the first deployment was in, where a stack update reported success and
    the host went on serving an older image.
    """
    dockerfile = _backend_dockerfile()
    assert "ARG PP_IMAGE_TAG" in dockerfile, "the image takes no build-time identity"
    assert "ENV PP_IMAGE_TAG=" in dockerfile, "the identity never reaches the running process"
    build = (DEPLOY / "deploy.sh").read_text(encoding="utf-8")
    assert "PP_IMAGE_TAG=${tag}" in build, (
        "the build never passes the tag it pushes, so the image would name a different commit "
        "or none at all"
    )


def test_a_release_reboots_the_host_and_then_checks_what_it_serves() -> None:
    """Deploying and having deployed are different claims, and only the second one matters.

    The host converges at boot, so a release is a parameter write and a reboot. Neither of
    those reports what the host ended up running, and the first release that assumed they did
    left the deployment serving an older image behind a stack that said ``UPDATE_COMPLETE``. So
    the stage rebooting the host is also the stage that reads ``/healthz`` back until it names
    the commit that was pushed, and fails if it never does.
    """
    build = (DEPLOY / "deploy.sh").read_text(encoding="utf-8")
    assert "stage_rollout ()" in build, "there is no stage that puts a new image on the host"
    rollout = build[build.index("stage_rollout ()") : build.index("stage_smoke ()")]
    assert "ec2 reboot-instances" in rollout, "nothing makes the host re-read anything"
    assert "/healthz" in rollout, "the rollout never checks what the host ended up serving"
    assert 'die "the host serves' in rollout, "a host that never converged would pass silently"
    sequence = build[build.index("  all)") :]
    assert sequence.index("stage_rollout") < sequence.index("stage_smoke"), (
        "the full deploy smoke-checks the deployment before it has rolled the new image out"
    )


# ------------------------------------------------------- one answer to "which image is this"


def _deploy_script() -> str:
    return (DEPLOY / "deploy.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """One shell function's body, so a property is asserted where it has to hold."""
    script = _deploy_script()
    opening = f"{name} () {{"
    assert opening in script, f"there is no {name}"
    start = script.index(opening)
    return script[start : script.index("\n}\n", start)]


def _stage(name: str) -> str:
    return _function(f"stage_{name}")


def _override_names(shell: str) -> list[str]:
    """The parameter names a stretch of the submission spells out, in the order it spells them.

    Every literal override in this script is ``"Name=${...}"``; the inherited ones are built as
    ``"${key}=${value}"`` and deliberately name nothing, which is what this cannot match.
    """
    return re.findall(r'"([A-Za-z]+)=\$', shell)


def _first_create_parameter_overrides() -> list[str]:
    """The parameters a submission reads out of this shell, which only a first create does.

    There is one list and it lives in ``create_stack_change_set``, because two stages submit
    this template -- a release and a host replacement -- and a second copy of the list would
    drift out of step with the first exactly where it is most expensive to be wrong. On an
    existing stack this branch is not taken at all: the same names are read back off the stack.
    """
    submit = _function("create_stack_change_set")
    return _override_names(submit[submit.index("\n  else\n") : submit.index("\n  fi\n")])


def _always_submitted_overrides() -> list[str]:
    """The parameters every submission names for itself, whether the stack exists or not."""
    submit = _function("create_stack_change_set")
    return _override_names(submit[submit.index("\n  fi\n") :])


def _stack_parameter_overrides() -> list[str]:
    """Every parameter name a submission can spell, from either branch."""
    return _first_create_parameter_overrides() + _always_submitted_overrides()


def test_the_stack_is_told_the_tag_this_run_pushed() -> None:
    """The control plane's answer and the registry's have to come from the same place.

    ``images``, ``config`` and ``stack`` each derive the tag from ``image_tag``, which is the
    commit and refuses a dirty tree. A stack stage that took it from anywhere else -- an
    argument, an environment variable, a moving ``latest`` -- could declare a commit whose image
    was never pushed, which is the same defect as declaring one that has been superseded and no
    easier to see from outside.
    """
    stack = _stage("stack")
    assert 'tag="$(image_tag)"' in stack, "the stack stage derives the tag from something else"
    assert '"ImageTag=${tag}"' in _function("create_stack_change_set"), (
        "the stack is never told which image this run pushed"
    )
    assert 'create_stack_change_set "$ami" "false" "$tag"' in stack, (
        "the release stage does not hand that tag to the submission"
    )
    for stage in ("images", "config"):
        assert "image_tag" in _stage(stage), f"stage_{stage} does not use the same tag"


def test_a_first_create_supplies_every_parameter_that_has_no_default(
    template: dict[str, Any],
) -> None:
    """Nothing may be left with no value at all on the one run that has nothing to inherit.

    A first create is the only submission that reads infrastructure out of the caller's shell,
    because there is no stack yet to read it off. So it is the branch that has to name every
    parameter with no default -- the ones with no value to fall back to -- and every name it
    uses has to be one the template declares, or the deploy fails at the point of use for a
    reason that was readable here.
    """
    declared = template["Parameters"]
    overrides = _first_create_parameter_overrides() + _always_submitted_overrides()
    required = {name for name, spec in declared.items() if "Default" not in spec}
    assert required <= set(overrides), (
        f"a first create supplies no value for {sorted(required - set(overrides))}"
    )
    assert set(overrides) <= set(declared), (
        f"the submission overrides {sorted(set(overrides) - set(declared))}, which the "
        "template does not declare"
    )


def test_a_submission_names_release_state_for_itself_and_inherits_the_rest() -> None:
    """The parameter-ownership split, asserted where it is written.

    Three parameters are the submission's own -- the release it names, the host image and the
    demo seed -- and they are passed explicitly by both stages because they are the only three
    either stage exists to move. Everything else is infrastructure: on an existing stack it is
    read back off that stack, so it cannot be named from here at all.

    The query that reads it back has to exclude exactly those three. Excluding one fewer would
    inherit the previous release over the top of this one; excluding one more would put an
    infrastructure parameter back in reach of this shell.
    """
    assert _always_submitted_overrides() == [
        "ImageTag",
        "HostAmiId",
        "SeedDemoFixtureOnFirstBoot",
    ], "a submission no longer names exactly the three parameters it owns"

    inherited = _function("inherited_stack_parameters")
    assert "describe-stacks" in inherited, (
        "the infrastructure is not read back off the stack at all"
    )
    excluded = set(re.findall(r"ParameterKey!='([A-Za-z]+)'", inherited))
    assert excluded == {"ImageTag", "HostAmiId", "SeedDemoFixtureOnFirstBoot"}, (
        f"the inherited-parameter query excludes {sorted(excluded)}; it must exclude exactly "
        "the three a submission owns"
    )
    assert "[ParameterKey,ParameterValue]" in inherited, (
        "the query returns something other than the key and the value it has to pass back"
    )

    submit = _function("create_stack_change_set")
    assert "inherited_stack_parameters" in submit, (
        "the submission does not read the live stack's parameters"
    )
    assert submit.index("stack_exists") < submit.index("inherited_stack_parameters"), (
        "the submission inherits before checking there is a stack to inherit from"
    )
    outside = submit.replace(submit[submit.index("\n  else\n") : submit.index("\n  fi\n")], "")
    for variable in ("PP_DEPLOY_VPC_ID", "PP_DEPLOY_INGRESS_CIDR", "PP_DEPLOY_DB_BACKUP_DAYS"):
        assert variable not in outside, (
            f"{variable} is read outside the first-create branch, so a release can still move it"
        )


def test_a_release_cannot_leave_the_stack_declaring_the_previous_commit() -> None:
    """The defect this guard was written after, and the only stage that can still close it.

    The three declarations of which image is deployed are written by three stages that each
    succeed alone: ``images`` pushes it, ``config`` writes the SSM parameter the host converges
    on, and ``stack`` records it in CloudFormation. Running the first two and then ``rollout``
    put the new image on the host, agreed with ``/healthz``, and left the stack declaring the
    previous commit -- which is the state the deployed stack was found in, declaring
    ``87f3a13f26a9`` while SSM and ``/healthz`` both said ``acfdd975dd4d``. So the stage that
    makes a release live compares all three first, and refuses instead of rebooting.
    """
    script = _deploy_script()
    assert "require_image_declarations_agree ()" in script, (
        "nothing compares the three declarations, so images, config and rollout still succeed "
        "with a stale stack"
    )
    rollout = _stage("rollout")
    assert 'require_image_declarations_agree "$tag"' in rollout, (
        "the rollout does not check the declarations it does not own"
    )
    assert rollout.index("require_image_declarations_agree") < rollout.index("reboot-instances"), (
        "the check runs after the host has already been rebooted onto the new image"
    )
    check = script[
        script.index("require_image_declarations_agree ()") : script.index("stage_preflight ()")
    ]
    assert "declared_image_tag" in check, "the stack's own declaration is never read back"
    assert "converged_image_tag" in check, "the parameter the host reads is never read back"
    assert check.count("|| die") == 2, "a disagreement is read and not refused"


def test_the_smoke_stage_refuses_a_deployment_whose_declarations_disagree() -> None:
    """Three answers in three places, and the check that has to see all of them.

    ``check_deployed_image`` compares the stack's declaration with ``/healthz``, and that is the
    only comparison the smoke script itself can make: it runs from outside AWS against a public
    origin and makes no AWS call. The SSM parameter is invisible to it, and a stack and a host
    that agree while SSM names something else are one reboot away from disagreeing. So the stage
    reads that third answer and fails before spending the HTTP checks.
    """
    smoke = _stage("smoke")
    assert 'declared="$(declared_image_tag)"' in smoke, "the stack's declaration is not read"
    assert 'converged="$(converged_image_tag)"' in smoke, "the SSM parameter is not read"
    assert '|| die "the stack declares $declared, SSM names $converged"' in smoke, (
        "the two are read and never compared"
    )
    assert 'PP_EXPECTED_IMAGE_TAG="$declared"' in smoke, (
        "the smoke script is not told which commit to expect, so the one check that compares "
        "the deployment with its declaration reports SKIPPED"
    )
    assert smoke.index("|| die") < smoke.index("deployment_smoke.py"), (
        "the HTTP checks run before the declarations are compared"
    )


def test_a_release_is_a_parameter_write_and_a_reboot_rather_than_a_new_instance() -> None:
    """``UserData`` runs once per instance, so nothing a release changes may live in it.

    A stack update carrying a new ``ImageTag`` reports ``UPDATE_COMPLETE`` and leaves the
    instance id unchanged; cloud-init does not run the bootstrap again. The image tag therefore
    reaches the host through the SSM parameter ``converge.sh`` re-reads at every boot, and the
    rollout is a reboot rather than an instance replacement. A rollout that deployed the stack,
    stopped and started the host, or replaced it would be a different and far more expensive
    claim than the one this stage makes.
    """
    rollout = _stage("rollout")
    assert "ec2 reboot-instances" in rollout, "nothing makes the host re-read anything"
    for expensive in ("cloudformation deploy", "update-stack", "run-instances", "terminate"):
        assert expensive not in rollout, (
            f"the rollout stage runs {expensive!r}; a release is a parameter write and a reboot"
        )
    assert "HostInstanceId" in rollout, (
        "the rollout does not reboot the instance the stack published, so it may be rebooting "
        "something else or nothing"
    )


# ------------------------------------------- what a release may not do to the host or the data
#
# The defect these were written after, and the one thing about this deployment that could still
# destroy everything in it. `deploy.sh stack` resolved the newest Amazon Linux 2023 arm64 image
# at every run so that no AMI id lived in git. ``ImageId`` is a replacement property on
# ``AWS::EC2::Instance``; an instance's first boot ends in ``compose run seed``; and ``pp
# reset-demo-state`` replaces every domain row in a database that deliberately outlives the host.
# So the first ordinary release after Amazon published a new image would have replaced the host
# and erased every case on it -- while reporting ``UPDATE_COMPLETE``.
#
# It was proved rather than argued: a change set built that way reported ``Replacement: True`` on
# the Host and on the EIPAssociation, and was deleted unexecuted. See
# docs/head-redeploy-2026-09-16.md section 7, and docs/non-destructive-release.md.


def test_a_release_passes_back_the_host_image_the_stack_already_declares() -> None:
    """A release may not choose an AMI, because choosing one replaces the instance.

    Not "should not": the release stage cannot reach the function that resolves a newer image.
    The value it passes is read back off the stack, so the only AMI an application release can
    name is the one the host is already running.
    """
    stack = _stage("stack")
    assert 'ami="$(release_host_ami_id)"' in stack, (
        "the release stage resolves its own host image again"
    )
    assert "latest_host_ami_id" not in stack, (
        "the release stage can still resolve the newest image, which replaces the instance"
    )
    resolver = _function("release_host_ami_id")
    assert "declared_host_ami_id" in resolver, (
        "the released AMI is not read back from the stack, so a release can still move it"
    )
    declared = _function("declared_host_ami_id")
    assert "ParameterKey=='HostAmiId'" in declared, (
        "declared_host_ami_id reads something other than the stack's own HostAmiId"
    )


def test_only_a_first_create_and_a_deliberate_upgrade_resolve_the_newest_image() -> None:
    """Three callers would be two too many.

    ``release_host_ami_id`` resolves the newest image on the branch where no stack exists -- a
    first create has nothing to preserve and no cases to lose -- and ``stage_host_image`` does
    it because that is what it is for. Anything else calling it is a path by which a release
    could pick up an AMI again.
    """
    script = _deploy_script()
    callers = {
        name
        for name in re.findall(r"^([a-z_]+) \(\) \{", script, flags=re.MULTILINE)
        if name != "latest_host_ami_id" and "latest_host_ami_id" in _function(name)
    }
    assert callers == {"release_host_ami_id", "stage_host_image"}, (
        f"the newest host image is resolved by {sorted(callers)}; only a first create and a "
        "deliberate host replacement may do that"
    )


def test_a_release_cannot_ask_for_a_seed_at_all() -> None:
    """The demo seed is a literal on the release path, not a variable.

    ``SeedDemoFixtureOnFirstBoot`` is what decides whether a new instance's first boot erases
    every case in the database. A release passes ``false`` written out in full, so there is no
    environment variable, no default and no leftover value by which a release could arm it.
    """
    stack = _stage("stack")
    assert 'create_stack_change_set "$ami" "false" "$tag"' in stack, (
        "the release stage does not pass a literal false for the seed"
    )
    assert "PP_DEPLOY_SEED_ON_FIRST_BOOT" not in stack, (
        "the release stage reads the seed variable, so a release can reseed after all"
    )
    assert '"SeedDemoFixtureOnFirstBoot=${seed}"' in _function("create_stack_change_set"), (
        "the submission never tells the stack whether to seed, so it keeps the previous value"
    )


def test_every_submission_builds_a_change_set_it_does_not_execute() -> None:
    """Nothing in this script may mutate the stack without a readable plan first.

    ``aws cloudformation deploy`` executes its change set by default, and that is the shape of
    the defect: the replacement was decided and applied in one call, with the only record of it
    arriving afterwards. There is one submission left in the script and it is preview-only.
    """
    script = _without_comments(_deploy_script())
    assert script.count("aws cloudformation deploy") == 1, (
        "there is more than one submission, so one of them may execute without a preview"
    )
    # Comment-stripped, because this function explains `--no-execute-changeset` in a comment
    # inside its own body and the flag being *described* is not the flag being passed.
    submit = _without_comments(_function("create_stack_change_set"))
    assert "--no-execute-changeset" in submit, (
        "the submission executes its own change set, so nothing can read it first"
    )


def test_a_release_refuses_a_change_set_that_would_replace_anything() -> None:
    """Read the plan, refuse the plan, delete the plan -- in that order and before executing.

    ``Remove`` counts with ``Replacement``: renaming a logical resource is reported as an Add
    and a Remove with no replacement flag, and that is a new instance too.
    """
    detector = _function("replaced_by_change_set")
    assert "ResourceChange.Replacement=='True'" in detector
    assert "ResourceChange.Action=='Remove'" in detector, (
        "a renamed resource is an Add and a Remove and would go unnoticed"
    )
    stack = _stage("stack")
    assert "replaced_by_change_set" in stack, "the release never reads what its plan would do"
    assert "discard_change_set" in stack, "a refused release leaves its change set behind"
    assert stack.index("replaced_by_change_set") < stack.index("execute_stack_change_set"), (
        "the release executes its change set before reading what it would replace"
    )
    refusal = stack[stack.index("replaced_by_change_set") : stack.index("execute_stack_change_set")]
    assert "|| die" in refusal or "die " in refusal, "a replacement is read and not refused"


# Exactly what `describe-change-set` returned for the change set built against `promisepatch-prod`
# on 2026-09-18: a release submitting this repository's template, with the AMI the stack already
# declares and `SeedDemoFixtureOnFirstBoot=false`. It was created, read, and deleted unexecuted.
#
# `Replacement` is not a boolean. The detector matched `True` alone, this payload says
# `Conditional`, and so the guard returned nothing and `stage_stack` would have executed a plan
# that may destroy the host. The stub two hundred lines below cannot find that, because it
# answers `describe-change-set` with the *result* of the query rather than with a payload the
# query runs against -- so the filter expression itself was never executed by any test. This one
# runs the script's own query, taken out of the script, against what AWS actually said.
LIVE_CHANGE_SET_THAT_MAY_REPLACE_THE_HOST: dict[str, Any] = {
    "Changes": [
        {
            "Type": "Resource",
            "ResourceChange": {
                "Action": "Modify",
                "LogicalResourceId": "ElasticIpAssociation",
                "ResourceType": "AWS::EC2::EIPAssociation",
                "Replacement": "Conditional",
                "Scope": ["Properties"],
                "Details": [
                    {
                        "Target": {
                            "Attribute": "Properties",
                            "Name": "InstanceId",
                            "RequiresRecreation": "Always",
                        },
                        "Evaluation": "Dynamic",
                        "ChangeSource": "ResourceReference",
                    }
                ],
            },
        },
        {
            "Type": "Resource",
            "ResourceChange": {
                "Action": "Modify",
                "LogicalResourceId": "Host",
                "ResourceType": "AWS::EC2::Instance",
                "Replacement": "Conditional",
                "Scope": ["Properties"],
                "Details": [
                    {
                        "Target": {
                            "Attribute": "Properties",
                            "Name": "UserData",
                            "RequiresRecreation": "Conditionally",
                        },
                        "Evaluation": "Dynamic",
                        "ChangeSource": "DirectModification",
                    }
                ],
            },
        },
    ]
}

# The same shape for a plan that genuinely replaces nothing, so the assertion below is that the
# query *discriminates* rather than that it matches everything it is shown.
LIVE_CHANGE_SET_THAT_REPLACES_NOTHING: dict[str, Any] = {
    "Changes": [
        {
            "Type": "Resource",
            "ResourceChange": {
                "Action": "Modify",
                "LogicalResourceId": "Host",
                "ResourceType": "AWS::EC2::Instance",
                "Replacement": "False",
                "Scope": ["Properties"],
                "Details": [],
            },
        }
    ]
}


def _replacement_query() -> str:
    """The `--query` the release guard actually sends, read out of the script."""
    found = re.search(r'--query "([^"]+)"', _function("replaced_by_change_set"))
    assert found is not None, "the replacement guard sends no --query"
    return found.group(1)


def test_a_conditional_replacement_is_refused_like_a_certain_one() -> None:
    """`Replacement` has three values and only one of them means "nothing will be replaced".

    `Conditional` is CloudFormation saying it cannot decide in advance -- the resource may be
    replaced when the plan runs. A release that treats a maybe as a no executes it, and for an
    `AWS::EC2::Instance` that maybe is the host. Unknown fails closed.
    """
    query = _replacement_query()
    replaced = jmespath.search(query, LIVE_CHANGE_SET_THAT_MAY_REPLACE_THE_HOST)
    assert replaced == ["ElasticIpAssociation", "Host"], (
        "a change set AWS says may replace the host reads as replacing nothing, "
        f"so a release would execute it; the guard returned {replaced!r}"
    )
    assert jmespath.search(query, LIVE_CHANGE_SET_THAT_REPLACES_NOTHING) == [], (
        "the guard refuses a plan that replaces nothing, so no release can ever run"
    )


def test_replacing_the_host_is_never_reached_by_a_release() -> None:
    """It is a named stage, and `all` does not name it."""
    script = _deploy_script()
    assert "stage_host_image () {" in script, "there is no deliberate way to replace the host"
    assert "host-image) stage_preflight; stage_host_image ;;" in script, (
        "the host-image stage is not reachable from the command line"
    )
    chain = script[script.index("  all)") : script.index("\n  *) die")]
    assert "stage_host_image" not in chain, (
        "`all` replaces the host, so an ordinary release run still destroys the instance"
    )
    for stage in ("stack", "rollout", "images", "config"):
        assert "stage_host_image" not in _stage(stage), f"stage_{stage} replaces the host"


def test_replacing_the_host_requires_naming_the_instance_it_destroys() -> None:
    """Visible before execution, and confirmed with something that cannot be left lying around.

    The confirmation is the id of the instance about to be destroyed. It cannot be guessed, it
    cannot survive from a previous run against a different instance, and it cannot be typed
    without having read the stack -- which is the point, because what is printed above it is
    the list of what dies.
    """
    host_image = _stage("host_image")
    assert "PP_DEPLOY_REPLACE_HOST" in host_image, "the replacement asks for no confirmation"
    assert '"${PP_DEPLOY_REPLACE_HOST:-}" != "$instance"' in host_image, (
        "the confirmation does not have to name the instance being destroyed"
    )
    assert host_image.index("replaced_by_change_set") < host_image.index(
        "PP_DEPLOY_REPLACE_HOST:-"
    ), "the confirmation is asked for before what it confirms has been read"
    assert host_image.index("PP_DEPLOY_REPLACE_HOST:-") < host_image.index(
        "execute_stack_change_set"
    ), "the instance is replaced before the confirmation is checked"
    assert "EVERY CASE IS ERASED" in host_image, (
        "a replacement that reseeds does not say that it erases the database"
    )
    assert 'tag="$(declared_image_tag)"' in host_image, (
        "replacing the host also moves the release, so the two are not separate operations"
    )


def test_the_first_boot_seed_is_gated_on_the_parameter(template: dict[str, Any]) -> None:
    """Two layers, because the database outlives the host.

    The bootstrap runs once per instance -- so on a *replacement* instance it runs against a
    database full of real cases. The invocation is inside a conditional, and the flag the
    application itself requires is written from the same parameter, so a hand-run
    ``compose run seed`` on a host provisioned without a seed is refused by the application
    rather than only by the bootstrap.
    """
    assert "SeedDemoFixtureOnFirstBoot" in template["Parameters"], (
        "nothing decides whether a new instance seeds"
    )
    spec = template["Parameters"]["SeedDemoFixtureOnFirstBoot"]
    assert spec["Default"] == "false", "a new instance seeds unless somebody says not to"
    assert sorted(spec["AllowedValues"]) == ["false", "true"]

    script = _user_data(template)
    assert "PP_ALLOW_FIXTURE_RESET=${SeedDemoFixtureOnFirstBoot}" in script, (
        "the seed's own permission is unconditional, so only the bootstrap gates the reset"
    )
    assert "PP_ALLOW_FIXTURE_RESET=true" not in script, (
        "the flag is still written true somewhere, which undoes the second layer"
    )
    guard = 'if [ "${SeedDemoFixtureOnFirstBoot}" = "true" ]; then'
    assert guard in script, "the first-boot seed runs unconditionally"
    assert script.index(guard) < script.index("run --rm -T seed"), (
        "the seed runs before the gate that is supposed to decide whether it runs"
    )


# The stages above are asserted by reading the script. These two run it.
#
# A static assertion says the refusal is spelled correctly; it cannot say the refusal fires.
# `stage_stack` is a sequence of command substitutions whose behaviour depends on what `aws`
# answers, and the one thing that matters -- that a change set replacing the host is refused
# before anything executes -- is a property of running it. So `aws` is replaced by a stub that
# answers from a scenario, the function definitions are sourced without the dispatch at the
# bottom, and the stage is called directly. No AWS call leaves the machine, and every call
# the stage makes is logged -- so "the release never asked EC2 for a newer image" is an
# assertion about a run rather than about a spelling.

FAKE_AWS = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$PP_FAKE_LOG"
all="$*"
case "$all" in
  *get-caller-identity*)          echo 111122223333 ;;
  *"ParameterKey=='HostAmiId'"*)  echo "$PP_FAKE_DECLARED_AMI" ;;
  *"ParameterKey=='ImageTag'"*)   echo "$PP_FAKE_DECLARED_TAG" ;;
  *"OutputKey=='HostInstanceId'"*) echo "$PP_FAKE_INSTANCE" ;;
  *describe-change-set*)          echo "$PP_FAKE_REPLACED" ;;
  *delete-change-set*)            echo deleted >> "$PP_FAKE_LOG.deleted" ;;
  *execute-change-set*)           echo executed >> "$PP_FAKE_LOG.executed" ;;
  *"cloudformation wait"*)        : ;;
  *"cloudformation deploy"*)
      echo "Changeset created successfully. Run the following command to review changes:"
      arn=arn:aws:cloudformation:us-east-1:111122223333:changeSet/awscli-1/abc
      echo "aws cloudformation describe-change-set --change-set-name $arn"
      ;;
  *"Stacks[0].Outputs"*)          echo "(outputs)" ;;
  *"Parameters[?ParameterKey!="*) printf '%s\\n' "$PP_FAKE_LIVE_PARAMETERS" ;;
  *describe-stacks*)              exit "$PP_FAKE_STACK_MISSING" ;;
  *ec2*describe-images*)          echo ami-07b9559027f889918 ;;
  *) echo "unstubbed aws call: $all" >&2; exit 98 ;;
esac
"""


# What the live stack declares, as `describe-stacks` returns it: one `key<TAB>value` row per
# parameter, the subnet list already comma-joined, and `TlsHostname` empty because the deployed
# stack derives its name from the address it allocated. Every value here is one the drifted
# shell below disagrees with.
LIVE_STACK_PARAMETERS = "\n".join(
    "\t".join(row)
    for row in (
        ("Environment", "prod"),
        ("VpcId", "vpc-live"),
        ("HostSubnetId", "subnet-live-host"),
        ("DatabaseSubnetIds", "subnet-live-a,subnet-live-b"),
        ("TlsHostname", ""),
        ("AllowedIngressCidr", "203.0.113.4/32"),
        ("InstanceType", "t4g.small"),
        ("DatabaseInstanceClass", "db.t4g.micro"),
        ("DatabaseStorageGiB", "20"),
        ("DatabaseBackupRetentionDays", "7"),
    )
)

# Every value the drifted shell would submit if it were still trusted. None of these may appear
# in a submission against an existing stack -- not one of them is a `Replacement` or a `Remove`,
# so the guard that reads the change set would not have caught a single one.
DRIFTED_SHELL_VALUES = (
    "vpc-drift",
    "subnet-drift-host",
    "subnet-drift-a",
    "subnet-drift-b",
    "0.0.0.0/0",
    "drift.example.com",
    "DatabaseBackupRetentionDays=1",
)


def _run_stage(stage: str, scenario: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Source the script's functions, without its dispatch, and call one stage against a stub."""
    executable = shutil.which("bash")
    if executable is None:
        pytest.skip("no bash on this machine to run the stage with")
    script = _deploy_script()
    directory = tempfile.mkdtemp()
    root = Path(directory)
    (root / "functions.sh").write_text(
        script[: script.index('case "$STAGE" in')], encoding="utf-8", newline="\n"
    )
    aws = root / "aws"
    aws.write_text(FAKE_AWS, encoding="utf-8", newline="\n")
    aws.chmod(0o755)
    # `image_tag` refuses a dirty tree and reads this repository's HEAD; neither is what is
    # under test, so it is overridden after sourcing.
    (root / "harness.sh").write_text(
        "set -euo pipefail\n"
        f". '{root.as_posix()}/functions.sh'\n"
        "image_tag () { printf 'aaaabbbbcccc'; }\n"
        f"{stage}\n",
        encoding="utf-8",
        newline="\n",
    )
    environment = {
        **os.environ,
        "PATH": f"{root.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "PP_FAKE_LOG": (root / "calls.log").as_posix(),
        "PP_FAKE_DECLARED_AMI": "ami-0fa4996c14e7d501e",
        "PP_FAKE_DECLARED_TAG": "b62779d6e975",
        "PP_FAKE_INSTANCE": "i-087c742587f83d61d",
        "PP_FAKE_REPLACED": "",
        "PP_FAKE_STACK_MISSING": "0",
        "PP_FAKE_LIVE_PARAMETERS": LIVE_STACK_PARAMETERS,
        # Deliberately none of the above. This is the drifted shell: every one of these differs
        # from what the live stack declares, so any of them reaching a submission against an
        # existing stack is the defect rather than a coincidence.
        "PP_DEPLOY_VPC_ID": "vpc-drift",
        "PP_DEPLOY_HOST_SUBNET": "subnet-drift-host",
        "PP_DEPLOY_DB_SUBNETS": "subnet-drift-a,subnet-drift-b",
        "PP_DEPLOY_INGRESS_CIDR": "0.0.0.0/0",
        "PP_DEPLOY_DB_BACKUP_DAYS": "1",
        "PP_DEPLOY_TLS_HOSTNAME": "drift.example.com",
        **scenario,
    }
    environment.pop("PP_DEPLOY_REPLACE_HOST", None)
    environment.pop("PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE", None)
    environment.pop("PP_DEPLOY_SEED_ON_FIRST_BOOT", None)
    environment.pop("PP_DEPLOY_HOST_AMI_ID", None)
    environment.update(scenario)
    result = subprocess.run(
        [executable, str(root / "harness.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=str(REPOSITORY_ROOT),
    )
    result.stdout += "\n--- calls ---\n" + (root / "calls.log").read_text(encoding="utf-8")
    if (root / "calls.log.executed").exists():
        result.stdout += "\nEXECUTED\n"
    if (root / "calls.log.deleted").exists():
        result.stdout += "\nDELETED\n"
    return result


def test_a_release_whose_plan_replaces_the_host_is_actually_refused() -> None:
    """Run it. The change set names the Host, and nothing may be executed.

    This is the 2026-09-16 change set, which reported ``Replacement: True`` on the Host and the
    EIPAssociation and was deleted by hand. Here the stage does it: refuses, deletes, exits
    non-zero, and never reaches `execute-change-set`.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_REPLACED": "Host\tElasticIpAssociation"})
    assert result.returncode != 0, "a release that would replace the host succeeded"
    assert "describe-images" not in result.stdout, "the release resolved its own host image"
    assert "Host" in result.stderr, "the refusal does not say what would be replaced"
    assert "EXECUTED" not in result.stdout, "the change set was executed anyway"
    assert "DELETED" in result.stdout, "the refused change set was left behind"


def test_a_release_that_replaces_nothing_executes_the_plan_it_read() -> None:
    """The other branch, and the parameters it submits.

    The AMI is the one the stack declared -- the stub exits 99 if anything asks EC2 for a newer
    image -- and the seed is `false`, which is what makes an application release unable to
    erase the database.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_REPLACED": ""})
    assert result.returncode == 0, result.stderr
    assert "EXECUTED" in result.stdout, "a clean release executed nothing"
    assert "DELETED" not in result.stdout, "a clean release deleted its own change set"
    assert "describe-images" not in result.stdout, (
        "the release asked EC2 for an image, so it can still pick up a newer one"
    )
    assert "HostAmiId=ami-0fa4996c14e7d501e" in result.stdout, (
        "the release submitted an AMI other than the one the stack declared"
    )
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout, (
        "the release did not submit a false seed"
    )
    assert "ImageTag=aaaabbbbcccc" in result.stdout


def test_replacing_the_host_without_the_confirmation_mutates_nothing() -> None:
    """The destructive stage, unconfirmed: it must print the damage and then refuse."""
    result = _run_stage("stage_host_image", {"PP_FAKE_REPLACED": "Host"})
    assert result.returncode != 0, "the host was replaced with no confirmation at all"
    assert "i-087c742587f83d61d" in result.stderr, (
        "the refusal does not name the instance whose id would confirm it"
    )
    assert "EXECUTED" not in result.stdout, "the host was replaced anyway"
    assert "DELETED" in result.stdout, "the refused change set was left behind"
    assert "ImageTag=b62779d6e975" in result.stdout, (
        "replacing the host also moved the release to this checkout's commit"
    )


# The same defect as the AMI, one parameter wider, and it survived the fix for the AMI.
#
# `release_host_ami_id` stopped a release resolving a newer `HostAmiId`, because moving that one
# replaces the instance and the replacement's first boot erased the database. But `HostAmiId` was
# never the only infrastructure parameter a release submitted: `VpcId`, `HostSubnetId`,
# `DatabaseSubnetIds`, `TlsHostname`, `AllowedIngressCidr` and `DatabaseBackupRetentionDays` were
# all rebuilt from `PP_DEPLOY_*` at every run. A shell that had lost `PP_DEPLOY_INGRESS_CIDR`
# since the last deploy therefore reopened 443 to the internet on the next release, and a shell
# still carrying `PP_DEPLOY_DB_BACKUP_DAYS=1` from a demo roll cut the database's recovery window
# to a day -- silently, under `UPDATE_COMPLETE`, and without tripping `replaced_by_change_set`,
# which only ever looked for a `Replacement` or a `Remove`.
#
# These run the stage against a stub whose live stack and whose shell disagree about every
# infrastructure value there is, and read what was actually submitted.


def test_a_release_submits_the_infrastructure_the_live_stack_declares() -> None:
    """The whole guarantee, in one run: the drifted shell reaches nothing.

    The stub's stack declares one set of infrastructure values and the shell holds a different
    one for every single parameter. What is submitted has to be the stack's, whole, and no value
    this shell holds may appear anywhere in the call.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_REPLACED": ""})
    assert result.returncode == 0, result.stderr
    for live in (
        "VpcId=vpc-live",
        "HostSubnetId=subnet-live-host",
        "DatabaseSubnetIds=subnet-live-a,subnet-live-b",
        "AllowedIngressCidr=203.0.113.4/32",
        "DatabaseBackupRetentionDays=7",
        "InstanceType=t4g.small",
        "DatabaseInstanceClass=db.t4g.micro",
        "DatabaseStorageGiB=20",
        "Environment=prod",
        # Empty, and still submitted. The deployed stack derives its name from the address it
        # allocated, so `TlsHostname` is the empty string -- and an implementation that skipped
        # empty values would hand that parameter back to the template's default instead of to
        # the stack, which is the same class of drift arriving from the other direction.
        "TlsHostname=",
    ):
        assert live in result.stdout, f"the release did not submit {live} as the stack declares it"
    for drifted in DRIFTED_SHELL_VALUES:
        assert drifted not in result.stdout, (
            f"this shell's {drifted} reached the submission, so local drift still changes the "
            "deployed infrastructure"
        )


def test_a_release_cannot_reopen_an_ingress_this_shell_forgot_about() -> None:
    """The narrowed range stays narrowed.

    ``AllowedIngressCidr`` is who may reach 80 and 443, its template default is the whole
    internet, and ``PP_DEPLOY_INGRESS_CIDR`` is optional -- so a shell that simply does not have
    it set used to submit ``0.0.0.0/0`` over the top of a deliberately narrowed stack. That is
    not a replacement and not a removal, so nothing in the release path would have refused it.
    """
    result = _run_stage("stage_stack", {"PP_DEPLOY_INGRESS_CIDR": "0.0.0.0/0"})
    assert result.returncode == 0, result.stderr
    assert "AllowedIngressCidr=203.0.113.4/32" in result.stdout, (
        "the release did not submit the ingress range the stack declares"
    )
    assert "AllowedIngressCidr=0.0.0.0/0" not in result.stdout, (
        "a release reopened 443 to the internet because this shell had the default set"
    )


def test_a_release_cannot_move_the_deployment_into_another_vpc_or_subnet() -> None:
    """Placement is the stack's, and the subnet list survives being read back and passed on.

    ``DatabaseSubnetIds`` is a ``List<AWS::EC2::Subnet::Id>``, which ``describe-stacks`` returns
    already comma-joined. It goes back as one argument with the comma inside it -- the same
    spelling a first create passes -- so reading it back cannot quietly turn two subnets into
    one argument per subnet, or one subnet named ``subnet-live-a,subnet-live-b``.
    """
    result = _run_stage(
        "stage_stack",
        {
            "PP_DEPLOY_VPC_ID": "vpc-drift",
            "PP_DEPLOY_HOST_SUBNET": "subnet-drift-host",
            "PP_DEPLOY_DB_SUBNETS": "subnet-drift-a,subnet-drift-b",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "VpcId=vpc-live" in result.stdout
    assert "HostSubnetId=subnet-live-host" in result.stdout
    assert "DatabaseSubnetIds=subnet-live-a,subnet-live-b" in result.stdout, (
        "the subnet list was not passed back as the one comma-joined value the stack declares"
    )
    assert "DatabaseSubnetIds=subnet-live-a subnet-live-b" not in result.stdout, (
        "the subnet list was split into separate arguments, which is a different parameter list"
    )
    for drifted in ("vpc-drift", "subnet-drift-host", "subnet-drift-a", "subnet-drift-b"):
        assert drifted not in result.stdout, f"a release submitted this shell's {drifted}"


def test_a_release_cannot_shorten_the_backup_window_a_demo_roll_left_behind() -> None:
    """A week of point-in-time recovery is not something a stale variable gets to spend.

    ``PP_DEPLOY_DB_BACKUP_DAYS`` exists because a Free Tier account cannot create the database
    with seven days, and docs/demo-world-roll.md tells an operator to set it to ``1``. A shell
    that has done that once used to carry it into every subsequent release of a stack that was
    created with seven.
    """
    result = _run_stage("stage_stack", {"PP_DEPLOY_DB_BACKUP_DAYS": "1"})
    assert result.returncode == 0, result.stderr
    assert "DatabaseBackupRetentionDays=7" in result.stdout, (
        "the release did not submit the retention the stack declares"
    )
    assert "DatabaseBackupRetentionDays=1" not in result.stdout, (
        "a release cut the database's recovery window to a day from a leftover variable"
    )


def test_a_release_still_submits_exactly_the_release_state_it_owns() -> None:
    """Inheriting everything else may not cost the three things a release is for.

    The tag is this run's commit, the host image is the one the stack already declares -- never
    a newer one, and the stub fails the run if anything asks EC2 for one -- and the seed is the
    literal ``false`` that keeps an application release unable to erase the database.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_REPLACED": ""})
    assert result.returncode == 0, result.stderr
    assert "EXECUTED" in result.stdout, "a clean release executed nothing"
    assert "ImageTag=aaaabbbbcccc" in result.stdout, "the release did not submit its own commit"
    assert "HostAmiId=ami-0fa4996c14e7d501e" in result.stdout, (
        "the release submitted an AMI other than the one the stack declared"
    )
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout, (
        "the release did not submit a false seed"
    )
    assert "describe-images" not in result.stdout, (
        "the release asked EC2 for an image, so it can still pick up a newer one"
    )


def test_a_release_that_can_read_no_stack_parameters_refuses_rather_than_resetting_them() -> None:
    """An empty read is a failure, not an empty stack.

    If the describe stops answering -- a permission lost, a query that no longer matches -- the
    submission would otherwise carry the three release parameters alone and let CloudFormation
    fall back for the rest, which is the defect arriving by a different door. It refuses, and
    refuses before submitting anything.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_LIVE_PARAMETERS": ""})
    assert result.returncode != 0, "a release with nothing to preserve submitted anyway"
    assert "cloudformation deploy" not in result.stdout, (
        "the submission was made before the refusal"
    )
    assert "EXECUTED" not in result.stdout, "something was executed"


def test_replacing_the_host_preserves_the_infrastructure_the_stack_declares() -> None:
    """The destructive stage inherits too, so it changes the host image and the host image only.

    ``host-image`` is the one operation allowed to replace the instance. That is not a licence
    to carry a drifted shell's VPC, ingress range or retention along with it.
    """
    result = _run_stage(
        "stage_host_image",
        {"PP_FAKE_REPLACED": "Host", "PP_DEPLOY_HOST_AMI_ID": "ami-07b9559027f889918"},
    )
    assert result.returncode != 0, "the host was replaced with no confirmation at all"
    assert "HostAmiId=ami-07b9559027f889918" in result.stdout, (
        "the deliberate upgrade did not submit the image it was given"
    )
    assert "AllowedIngressCidr=203.0.113.4/32" in result.stdout
    assert "VpcId=vpc-live" in result.stdout
    for drifted in DRIFTED_SHELL_VALUES:
        assert drifted not in result.stdout, (
            f"replacing the host carried this shell's {drifted} in with it"
        )


def test_a_first_create_provisions_from_the_configuration_it_is_given() -> None:
    """The one submission that has nothing to inherit, and must still be fully specified.

    No stack means no infrastructure to preserve and no cases to lose, so a first create reads
    placement, ingress and TLS out of the shell that is provisioning it and resolves the newest
    Amazon Linux 2023 arm64 image -- the only implicit resolution left in the script.
    """
    result = _run_stage("stage_stack", {"PP_FAKE_STACK_MISSING": "1"})
    assert result.returncode == 0, result.stderr
    assert "VpcId=vpc-drift" in result.stdout, "a first create ignored the VPC it was given"
    assert "HostSubnetId=subnet-drift-host" in result.stdout
    assert "DatabaseSubnetIds=subnet-drift-a,subnet-drift-b" in result.stdout
    assert "AllowedIngressCidr=0.0.0.0/0" in result.stdout
    assert "TlsHostname=drift.example.com" in result.stdout
    assert "DatabaseBackupRetentionDays=1" in result.stdout
    assert "describe-images" in result.stdout, (
        "a first create did not resolve an image, so it has no host to build"
    )
    assert "HostAmiId=ami-07b9559027f889918" in result.stdout
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout
    assert "vpc-live" not in result.stdout, "a first create read parameters off a stack"


def test_a_first_create_refuses_without_the_placement_it_cannot_read_anywhere() -> None:
    """And says which variable, because there is nothing to fall back to."""
    result = _run_stage("stage_stack", {"PP_FAKE_STACK_MISSING": "1", "PP_DEPLOY_VPC_ID": ""})
    assert result.returncode != 0, "a first create with no VPC submitted anyway"
    assert "PP_DEPLOY_VPC_ID" in result.stderr, "the refusal does not name what is missing"


def test_the_deployment_publishes_what_it_would_do_to_the_host_and_the_data(
    template: dict[str, Any],
) -> None:
    """Both non-release parameters are readable without describing the instance.

    ``DeclaredHostAmiId`` is what makes the release able to pass the AMI back rather than
    resolve one, and ``DemoFixtureSeededOnFirstBoot`` answers, before a host is replaced,
    whether the replacement's first boot would erase the database the old host leaves behind.
    """
    outputs = template["Outputs"]
    assert outputs["DeclaredHostAmiId"]["Value"] == {"Ref": "HostAmiId"}
    assert outputs["DemoFixtureSeededOnFirstBoot"]["Value"] == {"Ref": "SeedDemoFixtureOnFirstBoot"}


# --------------------------------------------- changing what the deployment is made of, on purpose
#
# `stage_stack` refuses any plan CloudFormation says may replace or remove a resource, and that
# refusal is correct. It also means the template in this checkout cannot reach the deployed stack
# through a release at all: applying it edits ``Host.UserData`` -- the seed gate itself -- and the
# live service answered ``Replacement: Conditional`` on the ``Host`` with the association's
# ``InstanceId`` at ``Always``. See docs/non-destructive-release.md section 9.3.
#
# So there has to be an operation that can carry a template change, and everything about it has to
# be the opposite of accidental. ``stage_infrastructure`` is that operation: it preserves the live
# release and the live host image, forces the seed off, inherits every infrastructure parameter
# off the stack, prints every resource the plan may destroy, and executes nothing until the
# operator types back the id of the instance being risked.
#
# What these tests hold is that it cannot be reached by a release, cannot be made to move release
# state, and cannot execute a destructive plan on its own.

# The three answers ``Replacement`` has, plus the rename that carries no replacement flag at all.
# The release guard has to refuse every one of them, and the deliberate stages read the same
# guard, so this is asserted against the query taken out of the script rather than against a stub
# that answers with the query's own result.
REPLACEMENT_ANSWERS_THAT_MUST_REFUSE: dict[str, dict[str, Any]] = {
    "certain": {"Action": "Modify", "LogicalResourceId": "Host", "Replacement": "True"},
    "conditional": {"Action": "Modify", "LogicalResourceId": "Host", "Replacement": "Conditional"},
    "renamed": {"Action": "Remove", "LogicalResourceId": "Host"},
}


@pytest.mark.parametrize("answer", sorted(REPLACEMENT_ANSWERS_THAT_MUST_REFUSE))
def test_a_release_refuses_every_answer_that_is_not_a_flat_no(answer: str) -> None:
    """``True``, ``Conditional`` and a bare ``Remove`` all mean the host may not survive.

    Only ``False`` means nothing will be replaced. The guard is one query and both deliberate
    stages read it too, so this is the one place the discrimination is checked.
    """
    change = {"Changes": [{"ResourceChange": REPLACEMENT_ANSWERS_THAT_MUST_REFUSE[answer]}]}
    assert jmespath.search(_replacement_query(), change) == ["Host"], (
        f"a change set whose replacement is {answer!r} reads as replacing nothing, so a release "
        "would execute it"
    )


def test_every_stage_that_submits_the_template_reads_the_same_replacement_guard() -> None:
    """One detector. A second one would be a second opinion about what destroys the deployment."""
    for stage in ("stack", "infrastructure", "host_image"):
        assert "replaced_by_change_set" in _stage(stage), (
            f"stage_{stage} submits the template without reading what its plan would do"
        )
    script = _without_comments(_deploy_script())
    guard = _without_comments(_function("replaced_by_change_set"))
    matched = "ResourceChange.Replacement"
    assert script.count(matched) == guard.count(matched), (
        "the replacement answers are matched outside the one guard, so two stages can disagree "
        "about what counts as destructive"
    )


def test_an_infrastructure_upgrade_is_never_reached_by_a_release() -> None:
    """A named stage that `all` does not name, and that no release stage calls."""
    script = _deploy_script()
    assert "stage_infrastructure () {" in script, (
        "there is no deliberate way to change the template"
    )
    assert "infrastructure) stage_preflight; stage_infrastructure ;;" in script, (
        "the infrastructure stage is not reachable from the command line"
    )
    chain = script[script.index("  all)") : script.index("\n  *) die")]
    assert "stage_infrastructure" not in chain, (
        "`all` changes the infrastructure, so an ordinary release run can carry a template change"
    )
    for stage in ("stack", "rollout", "images", "config", "host_image"):
        assert "stage_infrastructure" not in _stage(stage), f"stage_{stage} upgrades infrastructure"


def test_an_infrastructure_upgrade_cannot_move_the_release_or_arm_the_seed() -> None:
    """The two things it is structurally unable to do, asserted where they have to hold."""
    infrastructure = _stage("infrastructure")
    assert 'tag="$(declared_image_tag)"' in infrastructure, (
        "the upgrade does not read the release back off the stack, so it can move it"
    )
    assert "image_tag)" not in infrastructure.replace("declared_image_tag)", ""), (
        "the upgrade computes this checkout's tag, so it deploys a commit it never pushed"
    )
    assert 'create_stack_change_set "$ami" "false" "$tag"' in infrastructure, (
        "the upgrade does not pass a literal false for the seed"
    )
    assert "PP_DEPLOY_SEED_ON_FIRST_BOOT" not in infrastructure, (
        "the upgrade reads the seed variable, so an infrastructure change can reseed after all"
    )


def test_an_infrastructure_upgrade_resolves_no_image_of_its_own() -> None:
    """Preserving the AMI by default is not a policy here; the resolver is out of reach.

    ``test_only_a_first_create_and_a_deliberate_upgrade_resolve_the_newest_image`` pins the
    callers of ``latest_host_ami_id`` to two, and this stage is not one of them. Unset,
    ``PP_DEPLOY_HOST_AMI_ID`` means the value the stack declares.
    """
    infrastructure = _stage("infrastructure")
    assert "latest_host_ami_id" not in infrastructure, (
        "the upgrade can resolve a newer host image, which makes it a quieter host-image"
    )
    assert 'ami="${PP_DEPLOY_HOST_AMI_ID:-$declared}"' in infrastructure, (
        "the upgrade does not default the host image to the one the stack declares"
    )


def test_the_two_deliberate_confirmations_are_not_the_same_confirmation() -> None:
    """A shell holding one operation's confirmation may not spend it on the other.

    Both name the same instance id, so a single variable would mean an abandoned `host-image`
    attempt silently authorizes an infrastructure upgrade that may replace the host -- and the
    reverse. They are distinct variables, each read by exactly one stage.
    """
    infrastructure = _stage("infrastructure")
    host_image = _stage("host_image")
    assert '"${PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE:-}" != "$instance"' in infrastructure, (
        "the upgrade's confirmation does not have to name the instance being risked"
    )
    assert "PP_DEPLOY_REPLACE_HOST" not in infrastructure, (
        "the upgrade accepts the host-image confirmation, so one leftover variable spends on both"
    )
    assert "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE" not in host_image, (
        "host-image accepts the upgrade's confirmation, so one leftover variable spends on both"
    )
    assert infrastructure.index("replaced_by_change_set") < infrastructure.index(
        "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE:-"
    ), "the confirmation is asked for before what it confirms has been read"
    # Only the destructive branch asks for a confirmation -- a plan that replaces nothing runs
    # without one, which is the whole point of reading the plan first -- so the ordering is
    # asserted from the print that opens that branch rather than from the top of the stage.
    destructive = infrastructure[infrastructure.index("THIS PLAN MAY REPLACE OR REMOVE") :]
    assert destructive.index("PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE:-") < destructive.index(
        "execute_stack_change_set"
    ), "a plan that may replace the host executes before the confirmation is checked"


def test_the_confirmation_cannot_authorize_what_it_does_not_name() -> None:
    """The id names the host. It is not allowed to stand in for the database."""
    script = _deploy_script()
    found = re.search(r'INFRASTRUCTURE_MAY_REPLACE="([^"]*)"', script)
    assert found is not None, "nothing bounds what the upgrade's confirmation may authorize"
    assert sorted(found.group(1).split()) == ["ElasticIpAssociation", "Host"], (
        "the upgrade may confirm the replacement of something its confirmation does not name; "
        f"the list is {found.group(1)!r}"
    )


# The stubbed runs. Everything above says the stage is spelled correctly; these say it behaves.


def test_an_infrastructure_upgrade_preserves_the_release_and_the_host_image() -> None:
    """The stack declares `b62779d6e975` and `ami-0fa4996c14e7d501e`; both are what is submitted.

    The harness's `image_tag` returns `aaaabbbbcccc`, which is what a release would submit and
    what an upgrade may not, and the stub logs any call to `describe-images`.
    """
    result = _run_stage("stage_infrastructure", {"PP_FAKE_REPLACED": ""})
    assert result.returncode == 0, result.stderr
    assert "EXECUTED" in result.stdout, "a non-destructive upgrade executed nothing"
    assert "DELETED" not in result.stdout, "a non-destructive upgrade deleted its own change set"
    assert "ImageTag=b62779d6e975" in result.stdout, (
        "the upgrade moved the release to this checkout's commit"
    )
    assert "ImageTag=aaaabbbbcccc" not in result.stdout, (
        "the upgrade deployed a commit it never pushed an image for"
    )
    assert "HostAmiId=ami-0fa4996c14e7d501e" in result.stdout, (
        "the upgrade submitted an AMI other than the one the stack declared"
    )
    assert "describe-images" not in result.stdout, (
        "the upgrade asked EC2 for an image, so it can pick up a newer one and replace the host"
    )
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout


def test_an_infrastructure_upgrade_cannot_be_made_to_seed() -> None:
    """The one variable that erases every case is set, and reaches nothing."""
    result = _run_stage(
        "stage_infrastructure",
        {"PP_FAKE_REPLACED": "", "PP_DEPLOY_SEED_ON_FIRST_BOOT": "true"},
    )
    assert result.returncode == 0, result.stderr
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout, (
        "the upgrade did not submit a false seed"
    )
    assert "SeedDemoFixtureOnFirstBoot=true" not in result.stdout, (
        "an infrastructure upgrade armed the first-boot seed from a leftover variable"
    )


def test_an_infrastructure_upgrade_leaves_unrelated_infrastructure_where_it_is() -> None:
    """It changes the template. It does not change what the stack says the deployment is.

    The stub's shell disagrees with the live stack about every infrastructure value there is, and
    an upgrade is exactly the operation where "well, it is an infrastructure change" would be the
    excuse for letting one through.
    """
    result = _run_stage("stage_infrastructure", {"PP_FAKE_REPLACED": ""})
    assert result.returncode == 0, result.stderr
    for live in (
        "VpcId=vpc-live",
        "HostSubnetId=subnet-live-host",
        "DatabaseSubnetIds=subnet-live-a,subnet-live-b",
        "AllowedIngressCidr=203.0.113.4/32",
        "DatabaseBackupRetentionDays=7",
        "InstanceType=t4g.small",
        "DatabaseInstanceClass=db.t4g.micro",
        "DatabaseStorageGiB=20",
        "Environment=prod",
        "TlsHostname=",
    ):
        assert live in result.stdout, f"the upgrade did not submit {live} as the stack declares it"
    for drifted in DRIFTED_SHELL_VALUES:
        assert drifted not in result.stdout, (
            f"this shell's {drifted} reached an infrastructure upgrade, so local drift still "
            "changes the deployed infrastructure"
        )


def test_an_infrastructure_upgrade_whose_plan_may_replace_the_host_refuses_unconfirmed() -> None:
    """The live 2026-09-18 plan, unconfirmed: print what may die, refuse, delete, mutate nothing."""
    result = _run_stage("stage_infrastructure", {"PP_FAKE_REPLACED": "ElasticIpAssociation\tHost"})
    assert result.returncode != 0, "a plan that may replace the host executed unconfirmed"
    assert "THIS PLAN MAY REPLACE OR REMOVE" in result.stdout
    assert "ElasticIpAssociation" in result.stdout and "Host" in result.stdout, (
        "the refusal does not print what the plan may replace"
    )
    assert "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE=i-087c742587f83d61d" in result.stderr, (
        "the refusal does not name the instance whose id would confirm it"
    )
    assert "EXECUTED" not in result.stdout, "the plan was executed anyway"
    assert "DELETED" in result.stdout, "the refused change set was left behind"


def test_the_host_image_confirmation_does_not_authorize_an_infrastructure_upgrade() -> None:
    """The right id in the wrong variable is not a confirmation of this operation."""
    result = _run_stage(
        "stage_infrastructure",
        {
            "PP_FAKE_REPLACED": "ElasticIpAssociation\tHost",
            "PP_DEPLOY_REPLACE_HOST": "i-087c742587f83d61d",
        },
    )
    assert result.returncode != 0, "a host-image confirmation executed an infrastructure upgrade"
    assert "EXECUTED" not in result.stdout
    assert "DELETED" in result.stdout


@pytest.mark.parametrize(
    "confirmation",
    ["", "i-0000000000000dead", "yes", "true", "i-087c742587f83d61", "I-087C742587F83D61D"],
)
def test_only_the_exact_instance_id_confirms_a_destructive_upgrade(confirmation: str) -> None:
    """Not a yes, not a truncation, not a different instance, not the same id in another case."""
    result = _run_stage(
        "stage_infrastructure",
        {
            "PP_FAKE_REPLACED": "ElasticIpAssociation\tHost",
            "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE": confirmation,
        },
    )
    assert result.returncode != 0, f"{confirmation!r} executed a plan that may replace the host"
    assert "EXECUTED" not in result.stdout, f"{confirmation!r} executed the plan"
    assert "DELETED" in result.stdout, f"{confirmation!r} left its change set behind"


def test_a_confirmed_infrastructure_upgrade_executes_the_plan_it_read() -> None:
    """The deliberate path works, and still moves nothing but the template."""
    result = _run_stage(
        "stage_infrastructure",
        {
            "PP_FAKE_REPLACED": "ElasticIpAssociation\tHost",
            "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE": "i-087c742587f83d61d",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "EXECUTED" in result.stdout, "a confirmed upgrade executed nothing"
    assert "DELETED" not in result.stdout, "a confirmed upgrade deleted its own change set"
    assert "ImageTag=b62779d6e975" in result.stdout
    assert "HostAmiId=ami-0fa4996c14e7d501e" in result.stdout
    assert "SeedDemoFixtureOnFirstBoot=false" in result.stdout


def test_an_infrastructure_upgrade_refuses_to_replace_what_no_id_here_names() -> None:
    """Confirmed, correctly, and still refused: the id names the host, not the database.

    The confirmation is the strongest thing this operation can ask for, and it is still only an
    answer about one instance. A plan that proposes to replace the database is refused whatever
    is typed, because every case in the deployment is in it and nothing here names it.
    """
    result = _run_stage(
        "stage_infrastructure",
        {
            "PP_FAKE_REPLACED": "Database",
            "PP_DEPLOY_INFRASTRUCTURE_MAY_REPLACE": "i-087c742587f83d61d",
        },
    )
    assert result.returncode != 0, "a confirmed upgrade replaced the database"
    assert "Database" in result.stderr, "the refusal does not say what it would not replace"
    assert "EXECUTED" not in result.stdout, "the database was replaced anyway"
    assert "DELETED" in result.stdout, "the refused change set was left behind"


def test_an_infrastructure_upgrade_has_a_stack_to_upgrade_or_refuses() -> None:
    """It is an upgrade of an existing deployment; creating one is still `stack`."""
    result = _run_stage("stage_infrastructure", {"PP_FAKE_STACK_MISSING": "1"})
    assert result.returncode != 0, "an upgrade with no stack submitted anyway"
    assert "cloudformation deploy" not in result.stdout, "the submission was made before refusing"
    assert "EXECUTED" not in result.stdout


def test_an_explicitly_named_host_image_still_passes_through_the_confirmation() -> None:
    """The one thing an operator may change besides the template, and it is not a back door.

    Naming a different AMI is an explicit request, so the stage honours it -- and moving
    ``ImageId`` is what replaces the instance, so it arrives at the same confirmation as any
    other possible replacement rather than beside it.
    """
    result = _run_stage(
        "stage_infrastructure",
        {
            "PP_FAKE_REPLACED": "ElasticIpAssociation\tHost",
            "PP_DEPLOY_HOST_AMI_ID": "ami-07b9559027f889918",
        },
    )
    assert result.returncode != 0, "a host image change executed without confirmation"
    assert "HostAmiId=ami-07b9559027f889918" in result.stdout, (
        "the upgrade did not submit the image it was explicitly given"
    )
    assert "ami-0fa4996c14e7d501e -> ami-07b9559027f889918" in result.stdout, (
        "the upgrade does not print that it is moving the host image"
    )
    assert "EXECUTED" not in result.stdout
    assert "DELETED" in result.stdout


def test_replacing_the_host_is_still_exactly_what_it_was() -> None:
    """The new stage is beside `host-image`, not layered over it.

    ``host-image`` still resolves the newest image when given none, still asks for its own
    confirmation, still refuses without it, and still inherits the live infrastructure. The
    behavioural tests above this section assert the rest; this one holds the boundary.
    """
    host_image = _stage("host_image")
    assert 'ami="${PP_DEPLOY_HOST_AMI_ID:-$(latest_host_ami_id)}"' in host_image, (
        "host-image no longer resolves the newest image, so its semantics moved"
    )
    assert 'seed="${PP_DEPLOY_SEED_ON_FIRST_BOOT:-false}"' in host_image, (
        "host-image is no longer the stage that can seed, so the only reseed path moved"
    )
    assert "EVERY CASE IS ERASED" in host_image
    assert "stage_infrastructure" not in host_image, "host-image delegates to the upgrade stage"
    result = _run_stage("stage_host_image", {"PP_FAKE_REPLACED": "Host"})
    assert result.returncode != 0, "the host was replaced with no confirmation at all"
    assert "i-087c742587f83d61d" in result.stderr
    assert "EXECUTED" not in result.stdout
    assert "DELETED" in result.stdout


# ------------------------------------------------------------------ what the TLS proxy serves


def _caddy_directives() -> list[str]:
    """The Caddyfile with its explanation removed, so an example in a comment is not a route."""
    return [
        line.strip()
        for line in CADDYFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _handle_index(directives: list[str], directive: str) -> int:
    matches = [index for index, line in enumerate(directives) if line == directive]
    assert len(matches) == 1, f"{directive!r} appears {len(matches)} times; expected once"
    return matches[0]


def test_the_public_name_serves_the_page_rather_than_a_sentence_about_it() -> None:
    """The deployed root was a one-line 404 until the bundle had somewhere to be served from."""
    directives = _caddy_directives()
    catch_all = _handle_index(directives, "handle {")
    assert directives[catch_all + 1] == "reverse_proxy api:8000", (
        "the catch-all no longer reaches the process that holds the bundle"
    )
    assert "PromisePatch deployed loop" not in CADDYFILE_PATH.read_text(encoding="utf-8"), (
        "the placeholder landing response is still being served somewhere"
    )


def test_the_intent_api_is_refused_before_the_catch_all_can_publish_it() -> None:
    """The catch-all ends an allowlist, and `/internal*` is what the allowlist was keeping out.

    Without the refusal, `POST /internal/intents/report` from the public internet reaches the
    intent API with nothing in front of it but a service token the `api` container holds -- a
    published internal write surface rather than a hardened one.

    What makes the refusal win is Caddy's own ordering: it compiles `handle` blocks
    most-specific-first, so a path matcher always beats the catch-all whatever order they are
    written in. Checked against `caddy adapt`, which puts `/internal*` first and the unmatched
    block last. This asserts the written order anyway, because a reader checks a file rather
    than a compiled configuration, and a refusal written below the thing it refuses reads as
    dead code to whoever tidies it next.
    """
    directives = _caddy_directives()
    refusal = _handle_index(directives, "handle /internal* {")
    assert directives[refusal + 1] == "respond 404", "the refusal does not refuse"
    assert refusal < _handle_index(directives, "handle {"), (
        "the catch-all proxy is above the /internal refusal, so /internal is published"
    )


def test_every_other_route_still_wins_against_the_catch_all() -> None:
    """A catch-all added below a route changes nothing; added above one it swallows it."""
    directives = _caddy_directives()
    catch_all = _handle_index(directives, "handle {")
    for directive in (
        "handle /mcp* {",
        "handle /api* {",
        "handle /events* {",
        "handle /readyz {",
        "handle /healthz {",
    ):
        assert _handle_index(directives, directive) < catch_all, (
            f"{directive!r} is below the catch-all and would never be reached"
        )


# ------------------------------------------------------------------ the image the host runs


def _backend_dockerfile() -> str:
    return BACKEND_DOCKERFILE_PATH.read_text(encoding="utf-8")


def _bundle_copies() -> list[str]:
    return [
        line
        for line in _backend_dockerfile().splitlines()
        if line.startswith("COPY --from=frontend")
    ]


def test_the_backend_image_carries_the_browser_bundle() -> None:
    """One image tag moves the whole surface, so the bundle is built where the API is built.

    ADR-0012: the deployed host serves the single-page application from the backend image rather
    than from a seventh container, a third ECR repository or an S3 origin. If the build stage is
    ever dropped, the API keeps starting perfectly well and simply stops having a page to serve
    -- a failure nothing but loading the deployed site would find.
    """
    dockerfile = _backend_dockerfile()
    assert "AS frontend" in dockerfile, "the image no longer has a stage that builds the bundle"
    assert "npm ci" in dockerfile, "npm ci is what makes the bundle the committed lockfile's"
    assert "npm run build" in dockerfile, "nothing in the image builds the bundle"


def test_the_bundle_stage_is_built_for_the_machine_doing_the_building() -> None:
    """The host is Graviton, and emulating a Node toolchain to emit identical assets is cost.

    JavaScript, CSS and HTML are not architecture-specific. Without
    ``--platform=$BUILDPLATFORM`` an ``arm64`` build on an ``amd64`` machine runs the whole Node
    toolchain under emulation to produce byte-identical output.
    """
    assert "FROM --platform=$BUILDPLATFORM" in _backend_dockerfile(), (
        "the bundle stage would be emulated when the image is built for another architecture"
    )


def test_only_the_built_assets_leave_the_bundle_stage() -> None:
    """A Node runtime, a lockfile's worth of packages and the source are all build-time only."""
    copies = _bundle_copies()
    assert copies, "the runtime stage copies nothing from the bundle stage"
    for line in copies:
        assert "/dist" in line, f"{line!r} takes more than the built assets out of the stage"
        assert "node_modules" not in line


def test_the_runtime_is_pointed_at_the_directory_the_bundle_was_copied_to() -> None:
    """Two literals that must agree, in a place where disagreeing is silent.

    ``PP_STATIC_ROOT`` unset means the API serves no page at all, which is exactly what every
    test and the local Vite stack want -- and exactly what a deployed judge entry must not be.
    A typo in either literal produces that silence rather than an error.
    """
    copies = _bundle_copies()
    assert len(copies) == 1, f"{len(copies)} copies out of the bundle stage; expected one"
    destination = copies[0].split()[-1]
    configured = [
        line.split("=", 1)[1].strip()
        for line in _backend_dockerfile().splitlines()
        if line.startswith("ENV PP_STATIC_ROOT=")
    ]
    assert configured, (
        "the image copies the bundle in and never tells the API where it is, so it serves none"
    )
    assert configured == [destination], (
        f"the bundle is copied to {destination} and the API is pointed at {configured}"
    )


# ------------------------------------------------------------------------------- TLS and egress


@pytest.mark.parametrize("bypass", TLS_BYPASSES)
def test_nothing_in_the_deployment_disables_tls_verification(bypass: str) -> None:
    for path, text in _deploy_text().items():
        assert bypass not in text, (
            f"{path.relative_to(REPOSITORY_ROOT)} contains {bypass!r}. The deployment exists "
            "partly to prove real TLS; a bypass here would make the proof circular."
        )


def test_the_derived_hostname_is_the_stacks_own_address_and_nothing_else(
    template: dict[str, Any],
) -> None:
    """An empty ``TlsHostname`` must resolve to this stack's address, not to a third party.

    The parameter has an ordering problem the template cannot wish away: the address a DNS
    record would point at is allocated *by this stack*, so on a first deploy there is nothing to
    point a record at yet. The answer is to make the name out of the address -- sslip.io answers
    ``a.b.c.d.sslip.io`` with ``a.b.c.d`` for every address, so the record exists before the host
    asks for a certificate. What has to stay true is that the derived name is built from
    ``ElasticIp`` and from no other input: a name built from anything else would be a name
    somebody else controls, and the certificate would be issued to them.
    """
    derived = {"Sub": "${ElasticIp}.sslip.io"}
    condition = template["Conditions"]["DeriveTlsHostname"]
    assert condition == {"Equals": [{"Ref": "TlsHostname"}, ""]}, (
        "the derivation must be reached only by leaving the parameter empty"
    )

    supplied = _user_data_substitutions(template)
    assert supplied["TlsHostname"] == {
        "If": ["DeriveTlsHostname", derived, {"Ref": "TlsHostname"}]
    }, "the host would be told a different name than the outputs publish"

    for name, output in template["Outputs"].items():
        value = output["Value"]
        if not isinstance(value, dict) or "If" not in value:
            continue
        branch_condition, when_derived, _ = value["If"]
        assert branch_condition == "DeriveTlsHostname", f"{name} branches on something else"
        assert "${ElasticIp}" in json.dumps(when_derived), (
            f"{name}'s derived branch does not name this stack's own address"
        )


def test_the_derived_branch_is_a_name_and_not_a_way_around_a_certificate(
    template: dict[str, Any],
) -> None:
    """Deriving the name must not become a way to skip TLS, which is the whole temptation here.

    Both branches produce one hostname, both are served by the same Caddy block, and the
    ``https://`` origin published to clients is the same shape either way. The thing that would
    make this unsafe is an ``http://`` origin or an IP literal appearing on the derived side,
    because neither can carry a publicly trusted certificate.
    """
    for name, output in template["Outputs"].items():
        rendered = json.dumps(output["Value"])
        if "sslip.io" not in rendered:
            continue
        assert "http://" not in rendered, f"{name} publishes a plaintext origin"
        assert "${ElasticIp}.sslip.io" in rendered, (
            f"{name} publishes the bare address rather than the name the certificate is for"
        )


EC2_DESCRIPTION_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789. _-:/()#,@[]+=&;{}!$*"
)
"""What EC2 accepts in a security-group description. Notably absent: the apostrophe."""


def test_every_security_group_description_is_one_ec2_will_accept(
    template: dict[str, Any],
) -> None:
    """One apostrophe fails the whole stack, after the database has begun being created.

    EC2 validates rule and group descriptions against a fixed character set that does not
    include ``'``. There is no warning and no truncation: the rule is rejected, the stack rolls
    back, and everything created alongside it is deleted. Prose written for a reader is exactly
    where an apostrophe comes from, so this is checked here rather than discovered at minute
    nine of a deploy.
    """
    checked = 0
    for name, resource in template["Resources"].items():
        properties = resource.get("Properties", {})
        descriptions = [properties.get("GroupDescription"), properties.get("Description")]
        for key in ("SecurityGroupIngress", "SecurityGroupEgress"):
            descriptions += [rule.get("Description") for rule in properties.get(key, [])]
        if resource["Type"] not in {
            "AWS::EC2::SecurityGroup",
            "AWS::EC2::SecurityGroupIngress",
            "AWS::EC2::SecurityGroupEgress",
        }:
            continue
        for description in descriptions:
            if not isinstance(description, str):
                continue
            checked += 1
            rejected = sorted(set(description) - EC2_DESCRIPTION_CHARACTERS)
            assert not rejected, f"{name} describes itself with {rejected}, which EC2 rejects"
            assert len(description) < 256, f"{name}'s description is too long for EC2"
    assert checked >= 6, "the security groups describe themselves less than they used to"


def test_no_log_group_attribute_is_read_to_build_the_stack(template: dict[str, Any]) -> None:
    """``!GetAtt LogGroup.Arn`` is a ``logs:DescribeLogGroups`` call, and it is denied.

    ``DescribeLogGroups`` answers "which log groups exist" -- a question with no single resource
    -- so IAM evaluates it against the account, and the deployment role's grant is scoped to
    ``log-group:/promisepatch/*``. The attribute read is therefore refused and the resource that
    wanted it cannot be created. This is the same wrongly shaped grant P6.1 found on the
    developer role, in a second policy; the template stops depending on it instead, because the
    ARN is fully determined by the name the stack already chose.
    """
    rendered = json.dumps(template["Resources"])
    assert "LogGroup.Arn" not in rendered, (
        "something reads the log group's ARN as an attribute. Build it with Fn::Sub from "
        "AWS::Region, AWS::AccountId and the group name instead -- that needs no permission."
    )
    assert "logs:CreateLogStream" in rendered, "the runtime must still be able to ship output"


def test_an_unlisted_host_is_refused_in_a_way_a_client_can_read() -> None:
    """Caddy's "no site matched" default is an empty 200, and that is a false success.

    A request whose ``Host`` names something this deployment does not serve matches no site
    block, and Caddy answers it itself -- with ``200`` and an empty body, which a client cannot
    distinguish from a successful call. The request never reaches the protocol either way, so
    nothing is exposed by it; what is wrong is the status. A catch-all site says ``421`` instead.

    This does not move the authority boundary. For every request Caddy *does* pass through, the
    MCP server's own ``Host`` allowlist, ``Origin`` allowlist and bearer check are unchanged and
    still in front of the protocol, which is where P5.1 put them.
    """
    caddyfile = CADDYFILE_PATH.read_text(encoding="utf-8")
    assert ":443 {" in caddyfile, (
        "no catch-all site: an unlisted Host would get Caddy's empty 200 instead of a refusal"
    )
    tail = caddyfile[caddyfile.index(":443 {") :]
    assert "421" in tail, "the catch-all does not refuse"
    assert "reverse_proxy" not in tail, (
        "the catch-all proxies somewhere. It must answer and nothing else -- a site that "
        "matched any hostname and forwarded would be a second, unnamed way into the backend."
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
    # Retention is a parameter because an account on the AWS Free Tier plan cannot have the
    # intended week and RDS refuses the create. What must not become adjustable is *whether*
    # there are backups at all: 0 switches automated backups off, and point-in-time recovery
    # with them, so the floor is 1 and the default is still the week.
    retention = template["Parameters"]["DatabaseBackupRetentionDays"]
    assert properties["BackupRetentionPeriod"] == {"Ref": "DatabaseBackupRetentionDays"}
    assert retention["MinValue"] >= 1, "0 would mean no automated backups at all"
    assert retention["Default"] >= 1
    # The case state is the evidence a deployed loop happened. A mistyped `delete-stack` must
    # not be able to erase it without leaving a snapshot behind.
    assert template["Resources"]["Database"]["DeletionPolicy"] == "Snapshot"
    # And the other half, which is the one a release could reach: an update that replaced the
    # instance rather than deleting it. `deploy.sh stack` refuses any change set that replaces
    # anything, so a release cannot get here at all -- this is the second line, for the update
    # that arrives by some other hand.
    assert template["Resources"]["Database"]["UpdateReplacePolicy"] == "Snapshot"


def test_the_bootstrap_does_not_claim_to_run_on_every_boot(template: dict[str, Any]) -> None:
    """It runs once per instance, and saying otherwise sets up a wrong belief about releases.

    cloud-init's ``scripts-user`` module is once-per-instance, so a reboot re-reads none of the
    compose file, the TLS configuration, the secrets or the image tag. And ``UserData`` is not a
    replacement trigger for ``AWS::EC2::Instance``: a stack update carrying a new ``ImageTag``
    reports ``UPDATE_COMPLETE``, leaves the instance id unchanged, and the host goes on serving
    the image it first booted with. Both were observed. The comment claiming per-boot
    convergence was wrong, and a wrong comment here is how a release is believed deployed when
    it is not.
    """
    script = _user_data(template)
    assert "runs again on every boot" not in script, (
        "the bootstrap claims to converge at every boot; cloud-init runs it once per instance"
    )
    assert "runs once" in script, "it should say what it actually does"
    # And the convergence it cannot do itself has to be somewhere. The systemd unit runs at
    # every boot, so that is where a release reaches the host: the unit runs `converge.sh`,
    # which re-reads the composition, the TLS configuration and the image tag from SSM.
    assert "ExecStart=/opt/promisepatch/converge.sh" in script, (
        "the unit brings the stack up from whatever is on disk, so a release never reaches it"
    )
    for parameter in ("param compose", "param caddyfile", "param image-tag"):
        assert parameter in script, f"converge.sh never re-reads {parameter!r} from SSM"
    converge = script[script.index("CONVERGE") : script.index("chmod 0750")]
    assert "seed" not in converge, (
        "converge.sh seeds, and it runs at every boot -- which is the defect it was written "
        "after: a reboot that re-seeds erases the cases the deployment exists to preserve"
    )


def _converge_script(template: dict[str, Any]) -> str:
    """The script the systemd unit runs at every boot, as it will be written to disk."""
    script = _user_data(template)
    opening = "<<'CONVERGE'" + "\n"
    assert opening in script, "the bootstrap writes no converge script"
    closing = "\nCONVERGE\n"
    body = script[script.index(opening) + len(opening) : script.index(closing)]
    return body + "\n"


def test_the_bootstrap_runs_compose_where_the_composition_is(template: dict[str, Any]) -> None:
    """Compose reads the composition from the working directory, and the bootstrap starts in /.

    Observed, on a real host: the seed ran before anything had changed directory, compose found
    no composition, the line failed, and ``set -e`` took the rest of the bootstrap with it --
    including the systemd unit that had not been installed yet. The database was left unseeded,
    which is a deployment with no observer and therefore no way in for a judge.
    """
    script = _user_data(template)
    outer = (
        script[: script.index("<<'CONVERGE'")]
        + script[script.index("CONVERGE" + chr(10) + "chmod") :]
    )
    lines = outer.splitlines()
    entered = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("cd /opt/promisepatch"):
            entered = True
        if stripped.startswith("docker compose"):
            assert entered, (
                f"{stripped!r} runs before anything enters /opt/promisepatch, so compose has no "
                "composition to read"
            )


def test_the_restart_unit_is_installed_before_anything_that_can_fail(
    template: dict[str, Any],
) -> None:
    """The unit is how the host comes back, so it is installed before the host does anything else.

    A bootstrap that brought the stack up and then died would otherwise leave a host that serves
    until its next boot and never again -- which is exactly what one failing seed produced.
    """
    script = _user_data(template)
    # Named precisely: `systemctl enable --now docker` appears earlier in this script, and a
    # looser search would find that instead and pass whatever the order actually was.
    assert script.index("systemctl enable --now promisepatch") < script.index("run --rm -T seed"), (
        "the seed runs before the unit is installed, so a failing seed leaves a host that "
        "cannot restart"
    )


def test_the_converge_script_is_shell_a_shell_would_accept(template: dict[str, Any]) -> None:
    """A heredoc inside a heredoc inside a template, and the first boot is where it is read.

    Nothing before the instance exists parses this: CloudFormation checks the template, not
    the shell it carries, so a misplaced terminator or an unbalanced quote becomes a host that
    comes up with no stack on it and a log file only that host can read. This deployment has
    already spent five defects on things of exactly this shape.
    """
    executable = shutil.which("bash")
    if executable is None:
        pytest.skip("no bash on this machine to parse with")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "converge.sh"
        path.write_text(_converge_script(template), encoding="utf-8", newline="\n")
        parsed = subprocess.run(
            [executable, "-n", str(path)], capture_output=True, text=True, check=False
        )
    assert parsed.returncode == 0, "the converge script is not valid shell: " + parsed.stderr


def test_the_converge_script_reads_only_names_something_sets(
    template: dict[str, Any],
) -> None:
    """``set -u`` plus a name nothing writes is a boot that ends before it pulls anything."""
    converge = _converge_script(template)
    assert "set -euo pipefail" in converge, "a failing step would be stepped over"
    host_env = _env_file_block(template, "host.env <<EOF", "cat > /opt/promisepatch/converge.sh")
    written = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", host_env, re.M))
    assigned = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", converge, re.M))
    read = set(re.findall(r'"\$([A-Z][A-Z0-9_]*)"', converge))
    assert read, "the script reads no variable at all, which cannot be right"
    for name in sorted(read):
        assert name in written | assigned, (
            f"converge.sh reads {name}, which neither host.env nor the script itself sets"
        )


def test_the_host_requires_imdsv2_and_containers_can_still_use_the_role(
    template: dict[str, Any],
) -> None:
    """IMDSv2 is the control. The hop limit is not, and setting it to 1 broke the runtime.

    ``HttpTokens: required`` is what stops a token-less metadata read turning an
    application-layer request forgery into this host's credentials, and this host holds a
    Bedrock permission. That stays.

    The hop limit is a different thing, and this file previously asserted 1. Every process here
    runs in a container, the Docker bridge costs a hop, and at a limit of 1 the metadata
    response expires before it arrives -- so no container can obtain the instance role at all.
    Observed: the deployed worker's first Bedrock call returned ``NoCredentialsError`` in 2 ms
    without making a network request, while the host pulled images and read its secrets fine,
    because those run on the host. 2 is what AWS documents for containers on EC2. Above 2 the
    response can be relayed further than this host, so it is also a ceiling.
    """
    options = template["Resources"][HOST]["Properties"]["MetadataOptions"]
    assert options["HttpTokens"] == "required", "IMDSv2 is the control and is not negotiable"
    assert options["HttpPutResponseHopLimit"] == 2, (
        "1 leaves every container unable to reach IMDS; more than 2 relays beyond this host"
    )


def test_the_host_has_no_inbound_ssh_and_no_key_pair(template: dict[str, Any]) -> None:
    host = template["Resources"][HOST]["Properties"]
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
        # The newest one, and the only refusal here that used to be a side effect rather than a
        # decision: `/internal` was unreachable because the proxy named what it served and 404ed
        # the rest. Serving the page needs a catch-all, so the refusal became a line -- and a
        # line can be deleted, which is why it is now asserted against the running deployment.
        "check_internal_is_not_published",
    } <= names


@pytest.mark.parametrize("check_name", ["check_origin_refused", "check_protocol_revision"])
def test_a_check_that_cannot_be_performed_skips_rather_than_fails(check_name: str) -> None:
    """A missing local credential is not evidence that the deployment is broken.

    Both of these checks have to get *past* the bearer check to observe the thing they assert,
    so without ``PP_MCP_BEARER_TOKEN`` neither can be performed at all. ``check_protocol_revision``
    always said so; ``check_origin_refused`` reported FAILED with "status 401, expected 403",
    which reads as "the deployed origin guard is open". That fired against the live stack on
    2026-09-18 minutes after an infrastructure upgrade, on a deployment that was healthy and
    that smoked 12/12 the moment the token was supplied.

    The client is ``None`` on purpose: a skip must decide before it touches the network, so
    deleting the skip turns this into an ``AttributeError`` rather than a quiet pass.
    """
    from scripts import deployment_smoke

    check = getattr(deployment_smoke, check_name)
    outcome = check(
        None, deployment_smoke.Target(base_url="https://example.invalid", bearer_token=None)
    )
    assert outcome.outcome is deployment_smoke.Outcome.SKIPPED, (
        f"{check_name} claims a verdict about the deployment from a check it could not run"
    )
    assert "PP_MCP_BEARER_TOKEN" in outcome.detail, "the skip does not say what is missing"


def test_the_smoke_check_proves_the_deployment_is_the_one_that_was_deployed() -> None:
    """Up is not the same claim as current, and only the second one is about a release.

    A deployment that answers every endpoint perfectly while serving last week's image passes
    every availability check there is. These two are what make that a failure: the root has to
    serve the built page, and the running process has to name the commit the stack declares.
    """
    from scripts.deployment_smoke import CHECKS

    names = {check.__name__ for check in CHECKS}
    assert {"check_spa_at_root", "check_deep_link", "check_deployed_image"} <= names
    build = (DEPLOY / "deploy.sh").read_text(encoding="utf-8")
    assert "PP_EXPECTED_IMAGE_TAG=" in build, (
        "nothing tells the smoke check which commit the stack declares, so the one check that "
        "would catch a host serving an older image reports SKIPPED and the run still passes"
    )

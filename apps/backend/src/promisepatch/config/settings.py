"""Typed application settings, read from ``PP_``-prefixed environment variables.

Two rules keep this module honest as the system grows:

* **Only settings the code actually reads are declared.** A field here is a promise that
  something consumes it, and ``.env.example`` is asserted against this model in both
  directions, so a variable cannot drift into the example file or out of it unnoticed.
* **Nothing else reads the environment.** Modules take a :class:`Settings` instance; they do
  not reach for ``os.environ``. That is what makes the app configurable in tests without
  mutating global state.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Where this process is running. Controls exposure, not behaviour."""

    LOCAL = "local"
    AWS = "aws"


class LlmProvider(StrEnum):
    """Which semantic provider answers a bounded semantic job.

    A closed enum rather than a free string, so a deployment that misspells the value fails
    when its settings are parsed. There is no fallback branch: a process that cannot tell
    which provider it was configured with does not get to pick one.
    """

    FAKE = "fake"
    BEDROCK = "bedrock"


class Settings(BaseSettings):
    """The full configuration surface of the backend as it stands today."""

    model_config = SettingsConfigDict(
        env_prefix="PP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.LOCAL
    log_level: str = "info"
    cors_origins: str = "http://localhost:5173"

    database_url: SecretStr | None = None
    """The connection every request is served over: ``promisepatch_app``, and nothing more.

    Separate from :attr:`migration_database_url` on purpose rather than derived from it. The
    audited write boundary is only a control if the application cannot step over it, and an
    application holding the owner's credential could. Keeping the runtime connection a distinct
    variable means granting the API more privilege is an explicit act someone has to perform,
    not a side effect of how a URL was assembled.
    """

    migration_database_url: SecretStr | None = None
    """Admin/DDL connection, used by Alembic and by schema tests. Never by request handlers.

    A :class:`~pydantic.SecretStr` so the credential cannot reach a log line, a traceback or a
    ``repr`` by accident. The runtime connection is a separate, least-privileged role, whose
    password is :attr:`db_app_password`.
    """

    db_app_password: SecretStr | None = None
    """Password for ``promisepatch_app``, the least-privileged runtime role.

    Read in exactly two places: the migration that creates the role, and the database tests
    that connect as it to prove what it cannot do. The role's connection string is derived from
    the administrative one -- same host, same database, different login -- so there is one
    credential here rather than a second URI to keep in step.
    """

    session_secret: SecretStr | None = None
    """Key the ``pp_session`` cookie is signed with.

    Signing is what stops a browser handing us a session id it made up: the cookie carries an
    id and a MAC over it, and an id whose MAC does not verify is discarded before the database
    is asked about it. Rotating this value invalidates every outstanding cookie, which is the
    intended blunt instrument.
    """

    demo_worker_password: SecretStr | None = None
    """Password seeded for the demo baker login by ``pp reset-demo-state``."""

    demo_owner_password: SecretStr | None = None
    """Password seeded for the demo owner login by ``pp reset-demo-state``."""

    allow_fixture_reset: bool = False
    """Whether this deployment permits a fixture reset at all.

    Off by default, and deliberately not inferred from :attr:`env`. A reset deletes every
    domain row it owns; a process cannot work out from its own environment whether the database
    it is pointed at is the demo one, and guessing wrong destroys the wrong data. Turning this
    on is a statement by whoever configured the deployment, which is the only party that knows.
    """

    order_system_base_url: str | None = None
    """Where the external order system answers, or ``None`` when none is configured.

    The order system is the system of record for orders, so this is the address of another
    application rather than a feature flag. With it unset the amendment adapter has nowhere to
    send a governed recovery amendment, and the deployment falls back to the fake provider that
    proves the outbox's own guarantees and nothing about an order.

    Deliberately not defaulted to a local address. A default here would mean a deployment that
    forgot to configure its order system would quietly try to amend somebody's orders on
    whatever answered on that port.
    """

    order_system_webhook_secret: SecretStr | None = None
    """The shared secret an inbound order event is signed with.

    Service-to-service authentication, not a session: the sender is a server, it holds no
    cookie, and the ingress verifies an HMAC over the exact request body before it parses
    anything. A :class:`~pydantic.SecretStr` so it cannot reach a log line or a traceback, and
    with it unset the webhook endpoint refuses every delivery rather than accepting unsigned
    ones.
    """

    order_system_timeout_seconds: float = 10.0
    """How long one amendment call may take before it is treated as an uncertain delivery.

    Uncertain, not failed: the order system may well have applied it. The retry presents the
    same idempotency key, and the order system decides whether that is one effect or two.
    """

    llm_provider: LlmProvider = LlmProvider.FAKE
    """Which provider answers a semantic job. ``fake`` unless a deployment says otherwise.

    Defaulted to the fake on purpose, and not inferred from :attr:`env`. Every test, every CI
    job and the whole local Docker stack run without an AWS account, and they do so because
    the default is a provider that cannot reach one -- not because something noticed no
    credentials were configured and quietly degraded.
    """

    aws_region: str = "us-east-1"
    """The Region the Bedrock client is built for.

    Not a credential. Which account and which identity the call is made as is resolved by the
    AWS SDK's own credential chain at call time -- a profile, an SSO session, a task role --
    and PromisePatch holds no AWS key in any environment.
    """

    bedrock_model_id: str = "us.amazon.nova-2-lite-v1:0"
    """The one model, as ADR-0007 selects it: Nova 2 Lite via a cross-Region profile.

    One model for every job. No router, no tier ladder, no automatic escalation: five closed
    jobs do not need one, and a fallback chain would mean the answer a demo gets and the answer
    an eval measured came from different models.

    ADR-0004 named Claude Haiku 4.5 and this default named it with it. Haiku returned no
    readings in the P4.6 record -- not because it read badly, which was never measured, but
    because the Marketplace subscription this account needs cannot complete. A default naming a
    model this deployment cannot invoke is a configuration that fails on the first spoken turn,
    so it names the one that answers instead. The Bedrock transport is unchanged and Haiku
    remains a supported value of this variable.
    """

    bedrock_timeout_seconds: float = 10.0
    """How long one semantic call may take before it is abandoned.

    A bound rather than a target -- these calls sit inside a spoken turn and are expected in
    well under two seconds. What matters is that there is a ceiling at all: a workflow unit
    that could wait indefinitely on a model is a case that never resumes and a worker standing
    in a kitchen with no answer.
    """

    bedrock_max_attempts: int = 3
    """How many times the AWS SDK may retry one throttled or failed call, counting the first.

    Transport only. A malformed answer is not retried by this number: it gets exactly one
    corrective retry from the semantic gateway, because repeating an identical request until
    the schema happens to be satisfied is how invented data becomes accepted data.
    """

    explanation_verbalisation: bool = False
    """Whether a model is asked to phrase a user-facing explanation, or PromisePatch phrases it.

    Off, because the P4.8 explanation gate selected the deterministic renderer. The bounded
    verbalisation path passed every safety property it exists to protect -- no outcome or
    authority contradiction, no invented quantity, no unsupported option, faithfulness 5.00 --
    and did not reliably *say* a fact it was required to say: nine of twenty-one DEVELOPMENT
    passages cited a required fact in ``fact_refs`` while omitting it from the spoken words,
    after the one repair authorised to fix exactly that. Safe was established; complete was not.

    So the shipping passage is the one whose completeness is a property of the code rather than
    of a sample. This is a selection, not a deprecation: the verbalisation path, its prompt, its
    validator and its evidence are kept intact, and turning this on is how a later phase measures
    a different model or a repaired instrument without rebuilding any of it.

    Read by :func:`promisepatch.domain.verbalisation.explain`, which is the only production
    route to a passage. :func:`~promisepatch.domain.verbalisation.prepare` is the evaluated
    capability underneath it and is not governed by a deployment's setting -- an evaluation
    harness measures the model it was pointed at, whatever this deployment ships.
    """

    # ----------------------------------------------------------------- the conversation edge
    #
    # Two hops, two credentials, and one thing neither of them may carry. An MCP client
    # authenticates to the `mcp` process; the `mcp` process authenticates to the Intent API.
    # *Who is speaking* is configured on the server at the far end of both hops and is never
    # read off the wire, because a tool argument that could name an actor is an authority a
    # model would eventually be asked to choose.

    surface_worker_id: str | None = None
    """The staff member every intent arriving through the conversational surface is attested by.

    Server configuration, deliberately: this is the one place the actor behind an MCP tool call
    is decided, and it is decided by whoever deployed the process rather than by anything in a
    request. The Intent API refuses to serve an intent at all when it is unset -- an intake with
    no attestor would be a physical claim nobody made.

    One id today because one conversational surface exists. A deployment with several would map
    the *authenticated service principal* to a worker here; it would still be a lookup on the
    server, and a tool argument would still not appear in it.
    """

    internal_service_token: SecretStr | None = None
    """The shared secret the ``/internal/intents`` endpoints require of their caller.

    Service-to-service, not a session: the caller is the ``mcp`` process, it holds no cookie,
    and a cookie it did hold would make every tool call a cross-site request. A
    :class:`~pydantic.SecretStr` so it cannot reach a log line, and with it unset the Intent API
    answers every call ``503`` rather than accepting unauthenticated ones.
    """

    mcp_bearer_token: SecretStr | None = None
    """The bearer token an MCP client must present to the Streamable HTTP endpoint.

    The local and self-hosted inbound credential. A deployment on AgentCore Runtime replaces it
    with SigV4 at the edge, which is a hosting change rather than a protocol one; the tool
    surface, the envelope and the identity rule are the same either way. With it unset the MCP
    process refuses to start, because a server with no inbound credential is one that would
    accept a tool call from anyone who found the port.
    """

    mcp_allowed_origins: str = ""
    """Browser origins the MCP endpoint accepts, comma-separated. Empty means none.

    The spec's DNS-rebinding protection: a page on another origin must not be able to drive a
    locally bound MCP server. Empty by default and not derived from
    :attr:`cors_origins`, because the evidence UI and the tool endpoint are different surfaces
    with different callers, and inheriting one list into the other is how an origin ends up
    trusted somewhere nobody meant it to be. A request with no ``Origin`` at all -- every
    non-browser client -- is unaffected; it is authenticated by its bearer token like any other.
    """

    mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*"
    """``Host`` values the MCP endpoint accepts, comma-separated. ``:*`` matches any port.

    The other half of rebinding protection. Defaulted to loopback because that is where the
    development server binds; a deployment behind a real hostname sets its own.
    """

    mcp_intent_api_base_url: str | None = None
    """Where the Intent API answers, or ``None`` when this process has no engine to reach.

    The address of another application, not a feature flag, and deliberately not defaulted: a
    default here would mean an ``mcp`` process that was never configured would try to open cases
    on whatever answered on that port.
    """

    mcp_intent_timeout_seconds: float = 10.0
    """How long one intent call may take before the tool reports the engine unreachable.

    A timeout is an *unavailable reading*, never a reading: the tool answers with the
    ``ENGINE_UNAVAILABLE`` refusal rather than with a guess about what the engine would have
    said, and nothing is retried here, because the caller of a tool is a conversation and a
    conversation can ask again.
    """

    mcp_json_response: bool = False
    """Answer a tool call as one JSON body instead of an SSE stream.

    Off, so the development server exercises the same event-stream framing a real Streamable
    HTTP client meets. A host that cannot read ``text/event-stream`` turns it on; the JSON-RPC
    messages are identical either way.
    """

    orchestrator_mcp_url: str | None = None
    """Where the conversational orchestrator connects, as an ordinary MCP client would.

    The endpoint's own address -- ``http://127.0.0.1:8001/mcp`` locally -- and deliberately not
    derived from anything. The orchestrator is a client: it reaches the tools over the real
    transport with the same bearer credential any third-party client presents, so a deployment
    that pointed it somewhere else would be pointing a client somewhere else, which is a thing
    clients are for. Unset means this process has no tool surface to talk to, and ``pp
    converse`` says so rather than starting a conversation that cannot do anything.
    """

    orchestrator_timeout_seconds: float = 30.0
    """How long one tool call from the orchestrator may take before it is unreachable.

    Larger than the intent timeout it sits above, because it contains it: a client that gave up
    before the server it is waiting on would report unavailability for a call that was about to
    be refused for a reason worth hearing. It is still a ceiling -- a turn that never ends is a
    worker standing in a kitchen with no answer.
    """

    bakery_tz: str = "Africa/Tunis"
    """The bakery's local timezone.

    Read when an operator gives ``pp reset-demo-state`` a wall-clock anchor: "reset as if it is
    seven in the morning here" is the natural way to stage a demo, and it is a different instant
    depending on where "here" is. Every stored timestamp remains UTC.
    """

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL

    def require_database_url(self) -> str:
        """The runtime connection string, or a precise failure naming what to configure."""
        if self.database_url is None:
            raise RuntimeError(
                "PP_DATABASE_URL is not configured; set it to a postgresql+asyncpg:// URI "
                "that logs in as promisepatch_app before serving requests."
            )
        return self.database_url.get_secret_value()

    def require_migration_database_url(self) -> str:
        """The DDL connection string, or a precise failure naming what to configure."""
        if self.migration_database_url is None:
            raise RuntimeError(
                "PP_MIGRATION_DATABASE_URL is not configured; "
                "set it to a postgresql+asyncpg:// URI before running migrations."
            )
        return self.migration_database_url.get_secret_value()

    def require_db_app_password(self) -> str:
        """The runtime role's password, or a precise failure naming what to configure."""
        if self.db_app_password is None:
            raise RuntimeError(
                "PP_DB_APP_PASSWORD is not configured; "
                "set it before creating or connecting as the promisepatch_app role."
            )
        return self.db_app_password.get_secret_value()

    def require_session_secret(self) -> str:
        """The cookie signing key, or a precise failure naming what to configure.

        There is deliberately no generated fallback. A key invented at boot would work
        perfectly on one process and silently log every user out of a second one, and a
        constant default would mean anyone holding this source could forge a session.
        """
        return _required(self.session_secret, "PP_SESSION_SECRET")

    def require_demo_worker_password(self) -> str:
        """The demo baker's password, or a precise failure naming what to configure."""
        return _required(self.demo_worker_password, "PP_DEMO_WORKER_PASSWORD")

    def require_order_system_base_url(self) -> str:
        """The order system's address, or a precise failure naming what to configure."""
        if self.order_system_base_url is None:
            raise RuntimeError(
                "PP_ORDER_SYSTEM_BASE_URL is not configured; set it to the external order "
                "system's base URL before pushing a recovery amendment at it."
            )
        return self.order_system_base_url.rstrip("/")

    def require_order_system_webhook_secret(self) -> str:
        """The webhook signing secret, or a precise failure naming what to configure.

        There is deliberately no generated fallback and no unsigned mode. A webhook endpoint
        that accepted deliveries without a secret would accept them from anyone.
        """
        return _required(self.order_system_webhook_secret, "PP_ORDER_SYSTEM_WEBHOOK_SECRET")

    def require_bedrock_model_id(self) -> str:
        """The configured model, or a precise failure naming what to configure.

        Checked when the Bedrock provider is built, never when settings are parsed. A process
        configured for the fake has no business being asked for a model id, and a process on
        AWS should fail at construction with the variable's name rather than at the first
        spoken turn with a stack trace.
        """
        model_id = self.bedrock_model_id.strip()
        if not model_id:
            raise RuntimeError(
                "PP_BEDROCK_MODEL_ID is not configured; set it to the Bedrock model or "
                "cross-Region inference profile id before using PP_LLM_PROVIDER=bedrock."
            )
        return model_id

    def require_aws_region(self) -> str:
        """The Region for the Bedrock client, or a precise failure naming what to configure."""
        region = self.aws_region.strip()
        if not region:
            raise RuntimeError(
                "PP_AWS_REGION is not configured; set it to the Region whose Bedrock "
                "endpoint this deployment should call."
            )
        return region

    @property
    def order_system_configured(self) -> bool:
        """Whether this deployment has an external order system to talk to at all."""
        return self.order_system_base_url is not None

    def require_demo_owner_password(self) -> str:
        """The demo owner's password, or a precise failure naming what to configure."""
        return _required(self.demo_owner_password, "PP_DEMO_OWNER_PASSWORD")

    def require_surface_worker_id(self) -> str:
        """The conversational surface's attestor, or a precise failure naming what to configure."""
        if self.surface_worker_id is None:
            raise RuntimeError(
                "PP_SURFACE_WORKER_ID is not configured; the conversational surface has no "
                "worker to attest what it reports."
            )
        return self.surface_worker_id

    def require_internal_service_token(self) -> str:
        """The Intent API's service credential, or a precise failure naming what to configure."""
        return _required(self.internal_service_token, "PP_INTERNAL_SERVICE_TOKEN")

    def require_mcp_bearer_token(self) -> str:
        """The MCP endpoint's inbound credential, or a precise failure naming what to configure."""
        return _required(self.mcp_bearer_token, "PP_MCP_BEARER_TOKEN")

    def require_mcp_intent_api_base_url(self) -> str:
        """Where the Intent API answers, or a precise failure naming what to configure."""
        if self.mcp_intent_api_base_url is None:
            raise RuntimeError(
                "PP_MCP_INTENT_API_BASE_URL is not configured; the MCP server has no case "
                "engine to reach."
            )
        return self.mcp_intent_api_base_url.rstrip("/")

    @property
    def intents_configured(self) -> bool:
        """Whether this process can serve an intent at all: a token and an attestor."""
        return self.internal_service_token is not None and self.surface_worker_id is not None

    @property
    def mcp_allowed_origin_list(self) -> tuple[str, ...]:
        """``PP_MCP_ALLOWED_ORIGINS`` as a comma-separated list. Empty means no browser origin."""
        values = self.mcp_allowed_origins.split(",")
        return tuple(value.strip() for value in values if value.strip())

    @property
    def mcp_allowed_host_list(self) -> tuple[str, ...]:
        """``PP_MCP_ALLOWED_HOSTS`` as a comma-separated list."""
        return tuple(value.strip() for value in self.mcp_allowed_hosts.split(",") if value.strip())

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """``PP_CORS_ORIGINS`` as a comma-separated list.

        Deliberately a plain string on the model: pydantic-settings parses complex-typed
        fields as JSON, which would make the natural ``a,b`` form a startup error.
        """
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())


def _required(value: SecretStr | None, name: str) -> str:
    """Unwrap a configured secret, or say exactly which variable is missing."""
    if value is None:
        raise RuntimeError(f"{name} is not configured; set it before seeding the demo logins.")
    return value.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests construct :class:`Settings` directly instead."""
    return Settings()

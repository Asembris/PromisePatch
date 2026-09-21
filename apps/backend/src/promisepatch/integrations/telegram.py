"""The customer channel: one Bot API call, and nothing it could be mistaken for.

This module delivers a message PromisePatch has already decided to send, to a chat id
PromisePatch already stored, with words PromisePatch already composed. It is a transport, and
the list of what it is *not* is the design:

* **It grants no authority.** Delivering a proposal is not obtaining consent. Nothing here
  writes a row, opens a case, decides an option or touches an approval -- the import contract
  on :mod:`promisepatch.integrations` forbids this package the database and SQLAlchemy, so an
  adapter that wanted to record a customer's agreement could not.
* **It reads no reply.** There is no webhook here, no ``getUpdates``, no parser and no inbound
  path of any kind. A customer answers through the signed possession link the message carries,
  on the surface that already existed, into the consent protocol that already existed. Adding
  a second door through which the word ``YES`` could arrive would be adding a second consent
  parser, and there is exactly one.
* **It edits nothing it is given.** §13.6's wording is frozen, so the text goes out verbatim
  and is sent with no ``parse_mode`` at all -- Telegram must not read an asterisk in a recipe
  name as markup and quietly drop it. The signed link is appended on its own line, beside the
  words rather than inside them, exactly as the payload carries it.

**What it costs to be honest about idempotency.** The Bot API has no idempotency key:
``sendMessage`` called twice sends two messages, and there is no header, parameter or
after-the-fact query that would collapse them. The outbox states this case explicitly -- "where
a provider does not, the duplicate is real, and the attempt count on the row says so" -- and
this adapter is that case. What a retry cannot do is matter:

    the key is stable          -> one outbox row, one approval request, one link, one deadline
    the link is deterministic  -> both copies open the same question, not two
    consent is spent once      -> answering twice authorises nothing twice

So the duplicate is a second copy of one proposal on a customer's phone. It is never a second
proposal, a second authority or a second effect on an order. That is stated rather than
engineered around, because engineering around it here would mean inventing a claim the Bot API
does not support.

**Where the credential may appear.** In the URL of the outbound request, and nowhere else. It
is not in the client's ``base_url``, not in a logged field, not in a recorded error and not in
a ``repr``; transport failures are recorded by exception *type*, because an httpx error's own
message can carry the URL that failed -- and that URL is the token.

That last point is not a matter of discipline in this file alone, which is the awkward part.
The Bot API takes its credential in the request *path*, and an HTTP client logs the path it
called -- so an adapter that was careful everywhere in its own code would still publish the
token through its client's ordinary request log. :class:`_TokenRedaction` is the answer:
installed on the transport loggers while an adapter is open, removed when it closes, and
redacting rather than silencing, so other traffic still logs normally.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx2

from promisepatch.config import CustomerChannelProvider, Settings
from promisepatch.domain.model import EFFECT_MESSAGE_SEND, DeliveryOutcome, DeliveryStatus
from promisepatch.observability import get_logger

logger = get_logger(__name__)

API_ORIGIN: Final = "https://api.telegram.org"
"""The one host a bot token is ever sent to, as a constant rather than a setting.

Deliberately not configurable. Every other address in this application is a variable because
pointing it somewhere else is a legitimate deployment choice; pointing a bot credential
somewhere else is how a credential is stolen, and no deployment of this product needs to.
"""

CHANNEL_KIND: Final = "telegram"
"""The one channel kind this adapter will deliver to. A console or WhatsApp address is refused.

The vocabulary is :data:`promisepatch.db.types.CHANNEL_KINDS`, decoded onto the effect payload
by :mod:`promisepatch.graph.channel` in the transaction that queued the message. Checking it
here is what stops a deployment that switched its transport on from sending one customer's
message to a chat id that is really somebody else's WhatsApp number.
"""

CHAT_ID: Final = re.compile(r"^-?[0-9]{1,20}$")
"""A numeric chat id, negative for a group, and nothing else.

ADR-0006 makes the numeric chat id the customer's approval identity, and this refuses anything
that is not one. ``@username`` is deliberately not accepted even though the Bot API would take
it: a username is reassignable, so a message addressed to one is a message that could arrive at
whoever holds the name today rather than at the customer the request was created for.
"""

MAX_TEXT_CHARACTERS: Final = 4096
"""The Bot API's own ceiling on one message, checked here before the call rather than after.

Refused rather than truncated, and that is the whole reason the check is local. Telegram would
answer ``400`` and the outcome would be the same terminal failure -- but a version of this
adapter that trimmed the text to fit would be editing frozen wording, and the shortest thing
a customer could lose from the end of an approval request is the instruction telling them how
to answer it.
"""

DETERMINISTIC_STATUS: Final = frozenset({400, 401, 403, 404})
"""Answers that will not change if the identical call is made again.

``400`` is an unusable chat id or an unsendable message, ``401`` a bad bot token, ``403`` a bot
blocked or removed by the person on the other end, ``404`` a method this token cannot reach.
None of them is a reason to try five times: the outbox's failure continuation abandons the
approval and puts the promise on the owner's desk, which is the truthful outcome -- the
customer was not reached, and nobody may answer for them.
"""

GET_ME: Final = "getMe"
"""The Bot API method that reports which bot a credential is, and changes nothing by asking."""

GET_CHAT: Final = "getChat"
"""The Bot API method that reports whether one chat is known to the bot, and changes nothing.

Not ``getUpdates``: this asks about a destination, never about what anybody said to it.
"""

REDACTED: Final = "***"

TRANSPORT_LOGGERS: Final = ("httpx2", "httpcore")
"""The loggers an HTTP client writes a request line to, and therefore a bot token to.

Named rather than discovered, and the root logger deliberately not among them: a filter on
every logger in the process would rewrite records this module knows nothing about, which is a
larger change to an application's logging than hiding one credential should be.
"""


class _TokenRedaction(logging.Filter):
    """Replaces one bot token wherever a transport logger is about to print it.

    A filter rather than a level change, because silencing ``httpx2`` would take every other
    request line in the process down with it -- including the order system's, which an operator
    reading a failed amendment needs. This rewrites the record and lets it through.

    The record is flattened (``getMessage`` then empty args) because the token arrives as a
    formatting *argument*, not inside the format string, and a filter that only rewrote
    ``msg`` would redact nothing at all.
    """

    def __init__(self, token: str) -> None:
        super().__init__(name="promisepatch.telegram.redaction")
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        if self._token in rendered:
            record.msg = rendered.replace(self._token, REDACTED)
            record.args = ()
        return True


class TelegramAdapter:
    """The effect adapter the outbox dispatcher calls for a customer message.

    Same contract as every other provider: one :meth:`deliver` call, one
    :class:`~promisepatch.domain.model.DeliveryOutcome` back. The consent protocol does not know
    which adapter answered and must not: what a delivered message earns -- a track that waits,
    a deadline that governs -- is decided by the step the outbox row's continuation enqueues,
    against the row, exactly as it is for the fake provider.

    Anything that is not a customer message is refused terminally rather than guessed at, for
    the reason the order-system adapter refuses one: an adapter that quietly accepted an
    unfamiliar effect kind would report a success nobody performed.

    ``result`` is deliberately never set on the outcome. Telegram is a transport, not a system
    of record for anything PromisePatch later has to agree with, and
    :class:`~promisepatch.domain.model.DeliveryOutcome` reserves that field for a provider whose
    statement a recovery must verify. The message id travels in ``provider_ref``, which is what
    :func:`promisepatch.domain.approvals` reads back as durable proof the message went.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        timeout: float,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not bot_token.strip():
            raise ValueError("a Telegram adapter cannot be built with an empty bot token")
        self._token = bot_token
        self.timeout = timeout
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._redaction = _install_redaction(bot_token)

    def __repr__(self) -> str:
        """Names the channel and the timeout. Never the token, in a traceback or anywhere."""
        return f"TelegramAdapter(channel={CHANNEL_KIND!r}, timeout={self.timeout!r})"

    @classmethod
    def from_settings(cls, settings: Settings) -> TelegramAdapter:
        return cls(
            bot_token=settings.require_telegram_bot_token(),
            timeout=settings.telegram_timeout_seconds,
        )

    async def aclose(self) -> None:
        _remove_redaction(self._redaction)
        if self._owns_client:
            await self._client.aclose()

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome:
        """Send one message, and say what came back in the three words the outbox knows.

        The refusals above the network call are all deterministic by construction -- a wrong
        effect kind, a wrong channel, an unusable address, an unsendable message -- so they are
        terminal, and none of them costs a round trip or leaves a customer wondering.
        """
        if kind != EFFECT_MESSAGE_SEND:
            return _refused(f"the telegram adapter cannot deliver a {kind!r} effect")

        refusal = _unusable_destination(payload)
        if refusal is not None:
            return _refused(refusal)

        chat_id = str(payload["channel_address"])
        body = compose(text=str(payload["text"]), approval_url=payload.get("approval_url"))
        if len(body) > MAX_TEXT_CHARACTERS:
            return _refused(
                f"the message is {len(body)} characters and Telegram accepts "
                f"{MAX_TEXT_CHARACTERS}; it is refused rather than shortened"
            )

        outcome = await self._send(chat_id=chat_id, body=body)
        logger.info(
            # Neither the words nor the link. The text is a customer's own business and the
            # link is possession: a log line carrying one would hand an approval to whoever
            # reads the logs, which is precisely the party the signature exists to exclude.
            "worker.telegram.sent",
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            status=outcome.status.value,
            provider_ref=outcome.provider_ref,
            attempt_error=outcome.error,
        )
        return outcome

    async def _send(self, *, chat_id: str, body: str) -> DeliveryOutcome:
        """One ``sendMessage``, with no transaction held and no retry of its own.

        Retrying is the outbox's job and is done under the row's own key and ladder. An adapter
        that retried internally would spend attempts the row never counted, so a duplicate
        message would exist that nothing recorded.
        """
        try:
            response = await self._client.post(
                f"{API_ORIGIN}/bot{self._token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": body,
                    # The frozen wording is sent as text, never as markup: no ``parse_mode``
                    # anywhere in this call. An underscore in a recipe name is an underscore.
                    #
                    # Previews off so that Telegram's own crawler does not fetch the signed
                    # link. The page it would reach is a read and decides nothing, but a
                    # possession link is for the person who was sent it.
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=self.timeout,
            )
        except httpx2.HTTPError as error:
            # By type, never by message: an httpx error's text can carry the URL it failed on,
            # and that URL is the bot token. Uncertain rather than failed -- Telegram may have
            # sent the message before the answer was lost.
            return DeliveryOutcome(
                status=DeliveryStatus.RETRYABLE,
                error=f"telegram could not be reached: {type(error).__name__}",
            )

        return self._read(response, chat_id=chat_id)

    def _read(self, response: httpx2.Response, *, chat_id: str) -> DeliveryOutcome:
        """Turn one Bot API answer into the outbox's three-way vocabulary."""
        if response.status_code == 200:
            message_id = _message_id(response)
            if message_id is None:
                # The call completed and the answer is not one this build can read. Terminal
                # rather than retryable: the same call would produce the same unreadable
                # answer, and the promise belongs on the owner's desk rather than in a loop
                # that might put a third copy of the message on a customer's phone.
                return _refused(
                    f"telegram answered 200 with no message id: {self._safe(response.text[:200])}"
                )
            return DeliveryOutcome(
                status=DeliveryStatus.DELIVERED,
                provider_ref=f"telegram:{chat_id}:{message_id}",
            )

        detail = self._safe(_description(response) or f"HTTP {response.status_code}")
        if response.status_code in DETERMINISTIC_STATUS:
            return _refused(f"telegram refused this message: {detail}")
        # 429 included, deliberately. Telegram's ``retry_after`` is advice this build cannot
        # honour -- the row's own ladder decides when the next attempt happens -- so the wait is
        # recorded in the error rather than silently ignored.
        return DeliveryOutcome(
            status=DeliveryStatus.RETRYABLE,
            error=f"telegram answered {response.status_code}: {detail}",
        )

    def _safe(self, text: str) -> str:
        """Nothing that came off the wire reaches a row or a log with the token still in it.

        The Bot API does not echo the credential back, so this has nothing to do on any answer
        Telegram actually sends. It is here because "the provider will not do that" is a weaker
        guarantee than "and it would not matter if it did", and a secret in ``last_error`` is a
        secret in the database.
        """
        return text.replace(self._token, REDACTED)


def _install_redaction(token: str) -> _TokenRedaction:
    """Put one token's redaction on the transport loggers, and hand it back to be removed."""
    redaction = _TokenRedaction(token)
    for name in TRANSPORT_LOGGERS:
        logging.getLogger(name).addFilter(redaction)
    return redaction


def _remove_redaction(redaction: _TokenRedaction) -> None:
    """Take it off again. A filter left behind would outlive the credential it was hiding."""
    for name in TRANSPORT_LOGGERS:
        logging.getLogger(name).removeFilter(redaction)


class ChannelCheckError(RuntimeError):
    """Why a preflight could not confirm the channel, in words an operator may read aloud.

    Every message reaching this exception has been through :meth:`TelegramPreflight._safe`, or
    is composed here out of nothing that came off the wire. It is raised ``from None`` wherever
    an HTTP client's own exception is in scope, because that exception's text carries the URL it
    failed on -- and that URL is the bot token.
    """


@dataclass(frozen=True, slots=True)
class BotIdentity:
    """Who the credential says it is: the two fields that are safe to print, and no others.

    Not the whole ``getMe`` result. A bot's answer also reports what it is permitted to read in
    groups and whether it may be added to them, and a preflight that echoed the object back
    would be publishing provider detail nobody asked it to check.
    """

    id: int
    username: str


@dataclass(frozen=True, slots=True)
class ChatIdentity:
    """That one destination exists and what kind of place it is. Never who is in it.

    ``getChat`` answers with a title, a name and a photo for the person on the other end. None
    of that is needed to know the bot can reach them, and a customer's name in an operator's
    terminal is a customer's name in a scrollback buffer.
    """

    id: str
    type: str


class TelegramPreflight:
    """The two Bot API questions that change nothing, so a deployment can be checked cold.

    ADR-0006 records a rehearsed setup step -- the customer presses Start once, because bots
    cannot open a conversation -- and until now nothing verified it. This does, and the whole
    design is what it is unable to do:

    * **It cannot send.** There is no ``sendMessage`` here and no text to put in one. A
      preflight that could deliver would be a way to reach a real customer's phone from a
      terminal, outside the transaction that decides a message is owed.
    * **It cannot read a reply.** No ``getUpdates``, no webhook, no ``update_id``. The reason is
      the one :class:`TelegramAdapter` gives: a second door through which the word ``YES`` could
      arrive would be a second consent parser.
    * **It writes nothing anywhere.** No row, no file and no database handle -- the import
      contract on this package forbids it one -- and it needs no AWS credential to run.

    What it does is answer two questions an operator otherwise answers by sending a real message
    to a real person and watching a phone: is this credential a bot the API recognises, and is
    this exact chat id one the bot may speak to.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        timeout: float,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not bot_token.strip():
            raise ValueError("a Telegram preflight cannot be built with an empty bot token")
        self._token = bot_token
        self.timeout = timeout
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._redaction = _install_redaction(bot_token)

    def __repr__(self) -> str:
        """The channel and the timeout. Never the token, in a traceback or anywhere."""
        return f"TelegramPreflight(channel={CHANNEL_KIND!r}, timeout={self.timeout!r})"

    @classmethod
    def from_settings(cls, settings: Settings) -> TelegramPreflight:
        """Built from the credential and ceiling the adapter uses, or refused by variable name.

        Deliberately not gated on
        :attr:`~promisepatch.config.Settings.customer_channel_provider`. A preflight is what an
        operator runs *before* selecting Telegram, and one that demanded the deployment already
        be switched on could only ever confirm a decision that had already been made.

        The missing-credential refusal is worded here rather than borrowed from
        :meth:`~promisepatch.config.Settings.require_telegram_bot_token`, which speaks for a
        process that has already selected Telegram and would tell an operator to set a variable
        this command does not need.
        """
        if settings.telegram_bot_token is None:
            raise ChannelCheckError(
                "PP_TELEGRAM_BOT_TOKEN is not configured, so there is no bot credential to "
                "check. Setting it does not switch this deployment's transport on: "
                "PP_CUSTOMER_CHANNEL_PROVIDER decides that, separately."
            )
        return cls(
            bot_token=settings.require_telegram_bot_token(),
            timeout=settings.telegram_timeout_seconds,
        )

    async def aclose(self) -> None:
        _remove_redaction(self._redaction)
        if self._owns_client:
            await self._client.aclose()

    async def identify(self) -> BotIdentity:
        """Ask the API who this credential is, and refuse an answer that is not a bot."""
        return _bot_identity(await self._ask(GET_ME))

    async def locate(self, chat_id: str) -> ChatIdentity:
        """Ask whether the bot may speak to exactly this chat, refusing anything but an id.

        The address is checked against :data:`CHAT_ID` here as well as at the call site, for the
        reason the adapter checks it: ``@username`` is reassignable, so a preflight that
        confirmed one would be confirming reachability of whoever holds the name today.
        """
        if not CHAT_ID.match(chat_id):
            raise ChannelCheckError(f"{chat_id!r} is not a Telegram chat id")
        return _chat_identity(await self._ask(GET_CHAT, {"chat_id": chat_id}))

    async def _ask(self, method: str, body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """One read-only Bot API call, with its answer verified before anybody may believe it.

        ``getMe`` goes as a ``GET`` with no parameters at all; ``getChat`` carries its one
        argument in a JSON body rather than a query string, so a chat id does not end up in a
        URL that an intermediary would log.
        """
        url = f"{API_ORIGIN}/bot{self._token}/{method}"
        try:
            if body is None:
                response = await self._client.get(url, timeout=self.timeout)
            else:
                response = await self._client.post(url, json=dict(body), timeout=self.timeout)
        except httpx2.HTTPError as error:
            # By type, and ``from None``: the exception's own text, and the chain a bare
            # ``raise ... from error`` would keep, both carry the URL that failed -- and that
            # URL is the bot token.
            raise ChannelCheckError(
                f"telegram could not be reached for {method}: {type(error).__name__}"
            ) from None

        if response.status_code != 200:
            detail = self._safe(_description(response) or f"HTTP {response.status_code}")
            raise ChannelCheckError(f"telegram refused {method}: {detail}")

        try:
            answer = response.json()
        except ValueError:
            raise ChannelCheckError(
                f"telegram answered {method} with a body this build cannot read"
            ) from None

        if not isinstance(answer, dict) or answer.get("ok") is not True:
            raise ChannelCheckError(
                f"telegram did not answer ok to {method}: "
                f"{self._safe(_description(response) or 'no description')}"
            )

        result = answer.get("result")
        if not isinstance(result, dict):
            raise ChannelCheckError(f"telegram answered ok to {method} with no result object")
        return result

    def _safe(self, text: str) -> str:
        """Nothing off the wire reaches a terminal with the token still in it.

        Here for the reason :meth:`TelegramAdapter._safe` is: the Bot API does not echo the
        credential back, and "it would not matter if it did" is the stronger guarantee.
        """
        return text.replace(self._token, REDACTED)[:200]


def compose(*, text: str, approval_url: Any) -> str:
    """The frozen words, and the link beside them on its own line.

    Two properties, and both are the message contract rather than formatting. The text is
    reproduced exactly -- no prefix, no suffix, no rewrap -- because §13.6 froze it and a
    transport may not edit it. And the link is appended only where the payload carries one: a
    deployment that mints no link sends the words unchanged and loses nothing, since the two
    literal answers remain the whole protocol either way.
    """
    if not isinstance(approval_url, str) or not approval_url:
        return text
    return f"{text}\n\n{approval_url}"


def build_customer_channel(settings: Settings) -> TelegramAdapter | None:
    """The transport this deployment carries a customer message on, or ``None`` for the fake.

    The only reader of :attr:`~promisepatch.config.Settings.customer_channel_provider` in the
    whole application, so no transition and no handler can behave differently depending on
    which channel is configured. ``None`` means the caller keeps its fake provider, which is
    what every test, CI job and local ``docker compose up`` gets.

    Selecting Telegram with no credential raises here rather than returning ``None``. Falling
    back would be the worst of the available outcomes: a deployment that believed it was
    contacting customers, delivering to an in-memory provider, with approval requests marked
    sent and tracks waiting on answers nobody was ever asked for.
    """
    if settings.customer_channel_provider is CustomerChannelProvider.FAKE:
        return None
    return TelegramAdapter.from_settings(settings)


def _unusable_destination(payload: Mapping[str, Any]) -> str | None:
    """Why this message cannot be addressed, or ``None`` when it can.

    Every answer here is deterministic, so every one of them is a terminal failure. That is the
    honest reading: an address this adapter cannot send to will not become sendable on the
    fourth attempt, and pretending otherwise would delay the escalation the promise needs by
    the whole length of the retry ladder.
    """
    kind = payload.get("channel_kind")
    if kind != CHANNEL_KIND:
        return f"the telegram adapter cannot deliver to a {kind!r} channel"

    address = payload.get("channel_address")
    if not isinstance(address, str) or not CHAT_ID.match(address):
        return "the channel address is not a Telegram chat id"

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return "the effect carries no message to send"
    return None


def _bot_identity(result: Mapping[str, Any]) -> BotIdentity:
    """A ``getMe`` result, or a refusal naming the field that was not there.

    Checked field by field rather than trusted, because "the call returned 200" is not the
    question a preflight is asked. ``is_bot`` is verified explicitly: a credential that somehow
    described a person would mean the operator is holding something other than a bot token.
    """
    bot_id = result.get("id")
    if not isinstance(bot_id, int) or isinstance(bot_id, bool):
        raise ChannelCheckError("telegram's getMe answer carries no numeric bot id")
    if result.get("is_bot") is not True:
        raise ChannelCheckError("telegram's getMe answer does not describe a bot")
    username = result.get("username")
    if not isinstance(username, str) or not username:
        raise ChannelCheckError("telegram's getMe answer carries no bot username")
    return BotIdentity(id=bot_id, username=username)


def _chat_identity(result: Mapping[str, Any]) -> ChatIdentity:
    """A ``getChat`` result, reduced to the two fields that say the destination is real."""
    chat_id = result.get("id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        raise ChannelCheckError("telegram's getChat answer carries no numeric chat id")
    chat_type = result.get("type")
    if not isinstance(chat_type, str) or not chat_type:
        raise ChannelCheckError("telegram's getChat answer carries no chat type")
    return ChatIdentity(id=str(chat_id), type=chat_type)


def _refused(reason: str) -> DeliveryOutcome:
    return DeliveryOutcome(status=DeliveryStatus.TERMINAL, error=reason)


def _message_id(response: httpx2.Response) -> int | None:
    """The id Telegram gave the message it sent, or ``None`` if it did not say it sent one."""
    try:
        answer = response.json()
    except ValueError:
        return None
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        return None
    result = answer.get("result")
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    return message_id if isinstance(message_id, int) else None


def _description(response: httpx2.Response) -> str | None:
    """What Telegram said was wrong, when it said anything readable."""
    try:
        answer = response.json()
    except ValueError:
        return None
    if not isinstance(answer, dict):
        return None
    description = answer.get("description")
    return description if isinstance(description, str) else None


__all__ = [
    "API_ORIGIN",
    "CHANNEL_KIND",
    "CHAT_ID",
    "GET_CHAT",
    "GET_ME",
    "MAX_TEXT_CHARACTERS",
    "TRANSPORT_LOGGERS",
    "BotIdentity",
    "ChannelCheckError",
    "ChatIdentity",
    "TelegramAdapter",
    "TelegramPreflight",
    "build_customer_channel",
    "compose",
]

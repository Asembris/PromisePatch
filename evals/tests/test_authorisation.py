"""Authorising a charge is not the same act as running the live code path.

The distinction these tests pin down is the one whose absence produced three unintended model
calls. A flag said "take the live branch"; nothing said "a person accepted a bill". While the
model in question had no price, a pricing check happened to stand in for the missing consent.
The day it was priced, the substitute vanished and the only remaining obstacle was AWS.

So: the phrase is required, it names one scope, it is never inferred, and a test process
cannot construct a paid provider whatever it holds.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from evals.authorisation import (
    PHRASE_PREFIX,
    SpendAuthorisation,
    SpendNotAuthorisedError,
    SpendScope,
    authorise,
    refuse_real_inference_under_test,
    required_phrase,
    under_test,
)

EVERY_SCOPE = tuple(SpendScope)


# ------------------------------------------------------------------ the phrase is required


def test_no_phrase_is_a_refusal_for_every_scope() -> None:
    """``None`` is what the parser defaults to and what every test and CI job supplies."""
    for scope in EVERY_SCOPE:
        with pytest.raises(SpendNotAuthorisedError) as error:
            authorise(None, scope)
        assert "does not authorise a charge" in str(error.value)


def test_a_wrong_phrase_is_a_refusal() -> None:
    for scope in EVERY_SCOPE:
        with pytest.raises(SpendNotAuthorisedError):
            authorise("yes", scope)
        with pytest.raises(SpendNotAuthorisedError):
            authorise(PHRASE_PREFIX, scope)


def test_a_truthy_value_is_not_enough() -> None:
    """Not a boolean. A generic ``--confirm`` is a flag a script passes without reading it."""
    for value in ("true", "1", "yes", "confirm", "y", "TRUE"):
        with pytest.raises(SpendNotAuthorisedError):
            authorise(value, SpendScope.STAGE_A)


def test_the_right_phrase_produces_an_authorisation_carrying_its_ceilings() -> None:
    granted = authorise(
        required_phrase(SpendScope.STAGE_A),
        SpendScope.STAGE_A,
        max_calls=30,
        max_estimated_usd=Decimal("0.15"),
    )
    assert granted.scope is SpendScope.STAGE_A
    assert granted.max_calls == 30
    assert granted.max_estimated_usd == Decimal("0.15")
    assert granted.granted_at
    assert granted.as_payload()["scope"] == "STAGE-A"


# ------------------------------------------------------------------ scope does not carry


def test_a_phrase_for_one_scope_does_not_authorise_another() -> None:
    """The whole point of naming the scope in the phrase itself."""
    for scope in EVERY_SCOPE:
        for other in EVERY_SCOPE:
            if other is scope:
                continue
            with pytest.raises(SpendNotAuthorisedError) as error:
                authorise(required_phrase(scope), other)
            assert "does not name" in str(error.value)


def test_stage_a_approval_cannot_be_re_demanded_for_stage_b() -> None:
    """Checked again at the point of spending, not trusted from the parse."""
    granted = authorise(required_phrase(SpendScope.STAGE_A), SpendScope.STAGE_A)
    granted.require(SpendScope.STAGE_A)
    with pytest.raises(SpendNotAuthorisedError) as error:
        granted.require(SpendScope.STAGE_B)
    assert "does not carry to the next one" in str(error.value)


def test_every_scope_has_a_distinct_phrase() -> None:
    phrases = {required_phrase(scope) for scope in EVERY_SCOPE}
    assert len(phrases) == len(EVERY_SCOPE)
    assert all(phrase.startswith(PHRASE_PREFIX) for phrase in phrases)


def test_covers_is_exact_rather_than_hierarchical() -> None:
    """No scope contains another. Approving the probe never approves the whole split."""
    granted = SpendAuthorisation(scope=SpendScope.STAGE_A, granted_at="now")
    assert granted.covers(SpendScope.STAGE_A)
    others = [scope for scope in EVERY_SCOPE if scope is not SpendScope.STAGE_A]
    assert not any(granted.covers(scope) for scope in others)


# ------------------------------------------------------------------ never from the environment


def test_no_environment_variable_can_supply_the_authorisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator who exported something last week has not authorised anything today.

    Every name a person might reach for, set to the exact phrase, and the answer is still no:
    :func:`authorise` reads its argument and nothing else.
    """
    for name in (
        "PP_ALLOW_LIVE_EVAL",
        "PP_ALLOW_PAID_EVAL",
        "PP_AUTHORISE_PAID_INFERENCE",
        "PP_AUTHORIZE_PAID_INFERENCE",
        "AUTHORISE_PAID_INFERENCE",
        "PHRASE_PREFIX",
        "PP_SPEND_AUTHORISATION",
    ):
        monkeypatch.setenv(name, required_phrase(SpendScope.STAGE_A))
    with pytest.raises(SpendNotAuthorisedError):
        authorise(None, SpendScope.STAGE_A)


def test_the_authorisation_holds_no_secret_and_no_credential() -> None:
    """It is an intentionality gate, not authentication. Publishing it costs nothing."""
    payload = authorise(required_phrase(SpendScope.STAGE_B), SpendScope.STAGE_B).as_payload()
    assert set(payload) == {"scope", "granted_at", "max_calls", "max_estimated_usd"}


# ------------------------------------------------------------------ the process interlock


def test_this_process_is_recognised_as_a_test_process() -> None:
    assert under_test()


def test_a_test_process_may_not_construct_a_paid_provider() -> None:
    """The guard that does not care what the operator typed, and would have stopped the accident."""
    for scope in EVERY_SCOPE:
        with pytest.raises(SpendNotAuthorisedError) as error:
            refuse_real_inference_under_test(scope)
        assert "a test process may not construct a paid provider" in str(error.value)


def test_the_interlock_holds_with_a_valid_authorisation_and_full_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two independent guards, and the second does not consult the first.

    Everything an accidental live run had is arranged here -- a correct phrase, a priced
    model id, a complete set of AWS variables -- and the interlock still refuses, because
    none of those was ever the thing keeping a test process safe.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "FwoGZXIvYXdzEXAMPLETOKEN")
    monkeypatch.setenv("AWS_PROFILE", "promisepatch")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

    granted = authorise(required_phrase(SpendScope.STAGE_A), SpendScope.STAGE_A)
    with pytest.raises(SpendNotAuthorisedError):
        refuse_real_inference_under_test(granted.scope)


def test_the_interlock_is_read_from_the_runner_rather_than_a_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pytest`` in ``sys.modules`` is the primary signal; the env var is the second one."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert under_test()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    assert "PYTEST_CURRENT_TEST" in os.environ
    assert under_test()


# ------------------------------------------------------------------ no default anywhere


def test_no_fixture_or_default_grants_an_authorisation() -> None:
    """Absence, asserted. There is no module-level grant for a later test to inherit."""
    import evals.authorisation as module

    assert not any(isinstance(value, SpendAuthorisation) for value in vars(module).values())

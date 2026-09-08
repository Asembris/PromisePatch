"""Settings, and the contract between the model and ``.env.example``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from promisepatch.config import Environment, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
KEY = re.compile(r"^PP_([A-Z0-9_]+)=", re.MULTILINE)


def documented_keys() -> set[str]:
    return {match.lower() for match in KEY.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))}


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file()


def test_every_setting_is_documented() -> None:
    """A setting the code reads but the example omits is a variable nobody can discover."""
    assert set(Settings.model_fields) - documented_keys() == set()


def test_every_documented_variable_is_read() -> None:
    """A variable in the example that nothing reads is a promise the code does not keep."""
    assert documented_keys() - set(Settings.model_fields) == set()


def test_the_example_names_the_selected_runtime_model() -> None:
    """The model a reader copies out of the example is the model the code would have used.

    Two documents naming different models is how a deployment ends up measuring one and
    demonstrating another. ADR-0007 selects `us.amazon.nova-2-lite-v1:0` for both semantic jobs;
    both places say so or this fails.
    """
    documented = re.search(
        r"^PP_BEDROCK_MODEL_ID=(.+)$", ENV_EXAMPLE.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert documented is not None
    assert documented.group(1).strip() == Settings().bedrock_model_id
    assert Settings().bedrock_model_id == "us.amazon.nova-2-lite-v1:0"


def test_defaults_are_local() -> None:
    settings = Settings()
    assert settings.env is Environment.LOCAL
    assert settings.is_local


def test_environment_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_ENV", "aws")
    settings = Settings()
    assert settings.env is Environment.AWS
    assert not settings.is_local


def test_an_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_ENV", "staging")
    with pytest.raises(ValueError, match="env"):
        Settings()


def test_cors_origins_parse_as_a_comma_separated_list() -> None:
    settings = Settings(cors_origins="http://a.example, http://b.example ,")
    assert settings.cors_origin_list == ("http://a.example", "http://b.example")


def test_settings_are_immutable() -> None:
    with pytest.raises(ValueError, match="frozen"):
        Settings().env = Environment.AWS  # type: ignore[misc]


def test_fixture_resets_are_off_unless_someone_turns_them_on() -> None:
    """A reset deletes every domain row PromisePatch owns, so the default must be no."""
    assert Settings.model_fields["allow_fixture_reset"].default is False


def test_a_missing_demo_password_names_the_variable_to_set() -> None:
    settings = Settings(demo_worker_password=None, demo_owner_password=None)
    with pytest.raises(RuntimeError, match="PP_DEMO_WORKER_PASSWORD"):
        settings.require_demo_worker_password()
    with pytest.raises(RuntimeError, match="PP_DEMO_OWNER_PASSWORD"):
        settings.require_demo_owner_password()


def test_a_configured_demo_password_is_returned_unwrapped() -> None:
    settings = Settings(demo_worker_password="opens the door", demo_owner_password="so does this")
    assert settings.require_demo_worker_password() == "opens the door"
    assert settings.require_demo_owner_password() == "so does this"


def test_a_demo_password_does_not_leak_through_a_repr() -> None:
    """A secret that prints itself in a traceback is a secret in the logs."""
    assert "opens the door" not in repr(Settings(demo_worker_password="opens the door"))

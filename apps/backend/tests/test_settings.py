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

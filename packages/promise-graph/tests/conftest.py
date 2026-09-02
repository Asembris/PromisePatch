"""Shared fixtures and Hypothesis profiles.

Profiles are selected with ``HYPOTHESIS_PROFILE``: ``dev`` (default) is fast, ``ci`` is
derandomised so a CI failure is reproducible, ``long`` is for the nightly sweep that Phase 8
introduces.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=50, deadline=None)
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
settings.register_profile("long", max_examples=2000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def anchor() -> datetime:
    """A fixed reset instant. Behavioural tests that care about drift parametrise their own."""
    return datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

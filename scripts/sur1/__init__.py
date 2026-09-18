"""The ``SUR-1`` execution harness: the machinery that can drive three arms reproducibly.

This package is the driver the comparative benchmark record named as missing. It holds the run
manifest, the one adapter interface the three arms obey, the central budget and retry
enforcement, the receiver-side evidence collection, the immutable capture layout and the
check-5 ablation wrapper. It holds no metric definition, no ground truth and no scenario: those
are frozen in ``docs/benchmarks/safe-useful-recovery.v1.json`` and are read, never restated.

**It lives beside the scorer and outside every application.** ``scripts`` is not one of
import-linter's root packages and is not synced into the runtime image, so nothing deployed can
reach the ablation wrapper -- which is the structural half of the contract's promise that no
production file changes for arm C.

**The session that builds this is not the session that runs it.** Nothing here has been driven
against a ``SUR-1`` scenario, no model has been reached, and no comparative number exists.
"""

from __future__ import annotations

from typing import Final

DRIVER_VERSION: Final = "1.0.0"
"""Bumped whenever the driving or the evidence collection changes. Recorded in every capture."""

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

Recorded later: one scored run has since been taken, ``20260919T2020Z-scored`` on 2026-09-19. It is
published inconclusive and unaltered -- 24 of its 27 attempts ended ``HARNESS_FAILURE`` -- and
nothing here supersedes it. See ``docs/sur1-first-scored-run-defect.md``.
"""

from __future__ import annotations

from typing import Final

DRIVER_VERSION: Final = "1.1.0"
"""Bumped whenever the driving or the evidence collection changes. Recorded in every capture.

``1.0.0`` drove the first scored run, ``20260919T2020Z-scored``, which is preserved exactly as
it came out and is not superseded by anything here.

``1.1.0`` is the corrected execution revision: the durable worker is quiesced around a world
install and the installed world is read back before an arm is driven, and three capability
checks were added to the preflight. No frozen benchmark element moved -- not the manifest, the
prompt, the scorer, the ground truth, the budgets or the retry rules. See
``docs/benchmarks/sur1-execution-revision.v2.md``.
"""

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

Recorded later: two scored runs have since been taken. ``20260919T2020Z-scored`` on 2026-09-19 is
published inconclusive and unaltered -- 24 of its 27 attempts ended ``HARNESS_FAILURE``.
``20260920T1100Z-scored-corrected`` on 2026-09-20 failed in preparation on all 27 attempts,
reached no model and spent nothing. Nothing here supersedes either. See
``docs/sur1-first-scored-run-defect.md`` and ``docs/sur1-corrected-scored-run-refusal.md``.
"""

from __future__ import annotations

from typing import Final

DRIVER_VERSION: Final = "1.2.0"
"""Bumped whenever the driving or the evidence collection changes. Recorded in every capture.

``1.0.0`` drove the first scored run, ``20260919T2020Z-scored``, which is preserved exactly as
it came out and is not superseded by anything here.

``1.1.0`` is the corrected execution revision: the durable worker is quiesced around a world
install and the installed world is read back before an arm is driven, and three capability
checks were added to the preflight. No frozen benchmark element moved -- not the manifest, the
prompt, the scorer, the ground truth, the budgets or the retry rules. See
``docs/benchmarks/sur1-execution-revision.v2.md``.

``1.1.1`` is that revision with one defect removed, found by exercising it against the live
stack rather than against stand-ins: handing the worker back re-ran the service the worker
depends on, which is ``pp reset-demo-state``, so the resume destroyed the world the install had
just landed and ``verify`` had just confirmed. Neither run was taken under ``1.1.0``, so nothing
is reinterpreted. See ``docs/benchmarks/sur1-revision-v2-live-validation.md``.

``1.1.1`` drove the second scored run, ``20260920T1100Z-scored-corrected``, which is preserved
exactly as it came out. All 27 of its attempts failed in preparation, it reached no model and it
spent nothing.

``1.2.0`` is the database-target correction: the governed fixture load is handed the database it
writes to instead of resolving one of its own, and ``database_identity`` refuses a run whose load
and receivers name different databases before the run is authorised. No frozen benchmark element
moved -- not the manifest, the prompt, the scorer, the ground truth, the budgets or the retry
rules. Neither published run was taken under ``1.2.0``, so neither is reinterpreted. See
``docs/benchmarks/sur1-execution-revision.v3.md``.
"""

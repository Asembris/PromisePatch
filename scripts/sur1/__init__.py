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

Recorded later: three scored runs have since been taken and all three are preserved exactly as
they came out. ``20260919T2020Z-scored`` on 2026-09-19 is published inconclusive -- 24 of its 27
attempts ended ``HARNESS_FAILURE``. ``20260920T1100Z-scored-corrected`` on 2026-09-20 failed in
preparation on all 27 attempts, reached no model and spent nothing.
``20260920T1215Z-scored-v3`` on 2026-09-20 is published **invalid**: five arm-correlated defects
were later proved in it, none of which any preflight question asked about. Nothing here
supersedes any of them. See ``docs/sur1-first-scored-run-defect.md``,
``docs/sur1-corrected-scored-run-refusal.md``, ``docs/sur1-v3-forensic-audit.md`` and
``docs/sur1-parity-correction.md``.
"""

from __future__ import annotations

from typing import Final

DRIVER_VERSION: Final = "1.4.3"
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

``1.2.0`` drove the third scored run, ``20260920T1215Z-scored-v3``, which is preserved exactly as
it came out. It is published **invalid**: its baseline was never answered on any scenario, its
other two arms were driven at a contaminated world against a product holding the deterministic
fake, and its ablated arm was arm B by construction.

``1.3.0`` is the parity correction. The harness transport resolves one channel identity instead
of recording whichever spelling it was handed; the report tool publishes the frozen ``RunReport``
schema instead of a bare object; arm A's tool calls are captured as bounded diagnostics; the
installation lifecycle re-reads the world after the worker returns and refuses an undeclared
change; and the preflight grew seven questions, one of which -- ``ablation_reach`` -- refuses
every topology that exists today. No frozen benchmark element moved: not the manifest, the
prompt, the scorer, the ground truth, the budgets, the retry rules or a world program. No run has
been taken under it. See ``docs/sur1-parity-correction.md``.

``1.4.0`` is the hosted-worker topology, authorised by
``docs/adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md``. The product's own durable
worker -- ``promisepatch.worker.built`` driven by ``Worker.run_forever``, with no branch and no
benchmark flag -- runs inside the harness process for **both** arms B and C, and the
containerised worker is down for the whole run. Arm C's rebinding therefore reaches the process
that decides revalidation for the first time; the wrapper is held until the attempt's durable
work is quiescent; the product's own ``REVALIDATION_CHECK`` audit rows are read back to prove
which checks ran and which worker ran them; and the preflight grew three questions --
``build_identity``, ``config_parity`` and ``sole_executor`` -- which refuse a split-revision
stack, a split configuration and a second worker. No frozen benchmark element moved: not the
manifest, the prompt, the scorer, the ground truth, the budgets, the retry rules or a world
program, and ``implementation_sha`` is unmoved. No run has been taken under it.

``1.4.1`` is that topology with one defect removed, found the way ``1.1.1``'s was -- by
exercising it against the live stack rather than against stand-ins. ``ablation_reach`` and
``sole_executor`` ask their questions of a worker that is *running*, and nothing started one
until the first install, which happens inside ``drive`` and therefore after the gate. A fully
rebuilt, fully configured scored stack refused itself, for a reason that was true about the
ordering and false about the stack. ``execute`` now hosts the worker the run will use before the
gate asks, and puts it back down when the run is refused or when the invocation was only a
preflight. The dress rehearsal is wired to that same hosted worker, which it never was: it
controlled no worker at all, so arm C's wrapper reached nothing there either. Nothing about what
is measured moves -- no frozen benchmark element, no arm, no world, no reading rule, and
``implementation_sha`` is unmoved. No run has been taken under it. See
``docs/sur1-dr01-hosted-worker-rehearsal.md``.

``1.4.2`` is that seam with the install defect ``DR01`` found removed.
``InstallationLifecycle.fingerprint`` asked ``commitment_lines`` for a ``state`` column; the
table has ``received_state``, and the neighbouring ``production_tasks`` query is the one whose
column really is ``state``. It is fatal to every attempt of a scored run, because ``around``
fingerprints on every install, after the world has been written and verified. Nothing caught it
because nothing had executed the statement: the lifecycle tests answered from a dictionary and
``preflight.world_integrity`` drove the lifecycle against dictionaries too. So the statement is
corrected, that check's stand-in now refuses a column the product does not declare, the check
additionally executes the fingerprint's own statements against this machine's world database
when it answers, and a real migrated PostgreSQL schema is driven by
``scripts/tests/test_sur1_world_lifecycle_postgres.py``. Nothing about what is measured moves --
no frozen benchmark element, no arm, no world, no reading rule, no check was weakened,
``REQUIRED_CHECKS`` is still 28 and ``implementation_sha`` is unmoved. No run has been taken
under it. See ``docs/sur1-dr01-hosted-worker-rehearsal.md`` §4.

``1.4.3`` is the second defect ``DR01`` found removed, and it moves nothing a scored run does.
``tool_specifications`` derives arm A's report schema out of ``run_report_schema.fields``, and
the **rehearsal** document declared a ``report_outcome`` write without declaring that block, so
arm A died on a bare ``KeyError`` while arms B and C -- which never ask for a tool surface --
ran whole. Three things change and none of them is the reading of a contract that has the block:
the rehearsal document now carries its own ``run_report_schema``; a contract that carries none is
refused by name instead of escaping as a dictionary key, and is still refused rather than
defaulted or filled in from the frozen document; and ``tool_surface`` takes a contract so the
rehearsal's readiness gate can ask whether arm A's actions build before an attempt is started.
The frozen manifest has always carried the block, so the scored path derives exactly the schema
it derived at ``1.2.0``. No frozen benchmark element moved, no check was weakened,
``REQUIRED_CHECKS`` is still 28 and ``implementation_sha`` is unmoved. See
``docs/sur1-dr01-redrive.md`` §5.
"""

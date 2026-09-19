"""``DR01``'s contract, in the shape the driver reads, and pinned by its own hash.

:class:`~scripts.sur1.frozen.Contract` is a typed reading of a document plus the identity that
document was asserted under. The frozen reader builds one by asserting ``SUR-1``'s three
published hashes, which is exactly right for a scored run and exactly wrong for a rehearsal:
``DR01`` is not in that document and must never be put there.

So this module builds a :class:`~scripts.sur1.frozen.Contract` directly, over
``docs/rehearsals/dr01.v1.json``, carrying a :class:`~scripts.sur1.frozen.FrozenIdentity` whose
``benchmark_id`` is ``DR-REHEARSAL``. Every capture the rehearsal writes therefore says, in the
field a reader looks at first, that it is not ``SUR-1``.

**It is still hashed.** Not because a rehearsal needs a freeze, but because a resumed run is
refused when its identity fields moved, and that rule is one of the things this rehearsal exists
to exercise. The hash is recomputed with the frozen reader's own rule rather than a second one.

**It asserts the frozen contract is untouched.** :func:`load` recomputes ``SUR-1``'s published
manifest hash and refuses if it has moved. A rehearsal has no business editing the benchmark, and
a rehearsal that ran against an edited one would be the worst possible moment to find out.
"""

from __future__ import annotations

import json
from typing import Any, Final

from scripts.rehearsal import CONTRACT_PATH, REHEARSAL_ID, REHEARSAL_VERSION, SCENARIO
from scripts.sur1.frozen import (
    MANIFEST_PATH,
    PUBLISHED_MANIFEST_SHA,
    Contract,
    FrozenIdentity,
    FrozenIdentityError,
    manifest_sha,
)

SCORER_VERSION: Final = "rehearsal-1.0.0"
"""What the rehearsal scorer calls itself. Never a ``SUR-1`` scorer version."""


def document() -> dict[str, Any]:
    """The rehearsal document, read from disk. Reaches nothing else."""
    loaded: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if loaded["benchmark_id"] != REHEARSAL_ID or loaded["version"] != REHEARSAL_VERSION:
        raise FrozenIdentityError(
            f"{CONTRACT_PATH} is not {REHEARSAL_ID} v{REHEARSAL_VERSION}: it says "
            f"{loaded['benchmark_id']} v{loaded['version']}"
        )
    if [scenario["id"] for scenario in loaded["scenarios"]] != [SCENARIO]:
        raise FrozenIdentityError(
            f"the rehearsal document holds scenarios other than {SCENARIO}; a rehearsal is one "
            "synthetic scenario and is not a suite"
        )
    return loaded


def assert_benchmark_untouched() -> str:
    """Recompute ``SUR-1``'s published manifest hash, and refuse a rehearsal if it moved.

    The rehearsal does not read the frozen document for anything it needs. It checks it because
    the one thing a session building a parallel contract could plausibly do wrong is edit the
    real one, and the check costs a file read.
    """
    found = manifest_sha(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    if found != PUBLISHED_MANIFEST_SHA:
        raise FrozenIdentityError(
            f"the frozen SUR-1 contract has moved: published {PUBLISHED_MANIFEST_SHA}, "
            f"recomputed {found}. A dress rehearsal does not run against an edited benchmark."
        )
    return found


def load() -> Contract:
    """The rehearsal contract, with its own identity and the benchmark's own hash checked."""
    assert_benchmark_untouched()
    loaded = document()
    return Contract(
        identity=FrozenIdentity(
            benchmark_id=REHEARSAL_ID,
            manifest_version=str(loaded["version"]),
            manifest_sha=manifest_sha(loaded),
            baseline_prompt_sha="not-applicable-to-a-rehearsal",
            scorer_version=SCORER_VERSION,
        ),
        document=loaded,
    )


def scenario() -> dict[str, Any]:
    """``DR01`` itself, including the rehearsal expectations the rehearsal scorer reads."""
    return load().scenario(SCENARIO)


__all__ = ["SCORER_VERSION", "assert_benchmark_untouched", "document", "load", "scenario"]

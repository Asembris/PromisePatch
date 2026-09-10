"""The identity of the plan a worker is being shown, so a yes can only mean *that* plan.

A confirmation is the one authority in the whole conversational surface that is not the
engine's own bookkeeping: a person said yes, and recoveries execute because of it. What that
yes is worth depends entirely on it being attached to something specific. A confirmation that
carries only a case id authorises whatever the case happens to hold when it arrives -- which
is not what the worker read out, and on a re-planned case is not even the same set of orders.

So the plan a case is presenting has a **derived identity**, and confirming quotes it back.

**Derived, never stored.** There is no ``plan_id`` column. The identity is recomputed from the
durable rows every time it is needed, which is what makes a mismatch mean something: it says
the rows moved, not that a cache went stale. Storing it would create a second answer to "what
plan is this" and eventually the two would disagree with nothing to say which was right.

**Over the whole case, not only the recoverable part.** The digest covers the case version and
every track -- untouched ones included -- because "these three change and these three do not"
is the claim the worker is confirming. A promise that quietly joined or left the untouched band
between the reading and the yes has changed what was agreed to.

**Opaque and one-way.** A hex digest, and nothing a caller can take apart or construct. It
names a plan the server rendered; it cannot be used to *describe* a plan the server did not,
and it carries no recipe version, order or customer that a model could reach through it.

Pure: stdlib only, no rows, no clock, no environment. An import-linter contract of the same
name keeps it that way.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

PLAN_IDENTITY_VERSION: Final = "1"
"""Mixed into the digest, so a change to what a plan identity *covers* cannot silently make an
old identity match a new plan. A build that computed identities differently produces different
ones, and every confirmation quoting an old one fails closed."""


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One track, in exactly the terms that decide whether the plan is still the same one.

    Deliberately small. Not every column of a track belongs here: a change to something the
    worker was never shown -- a retry count, a timestamp -- would invalidate a confirmation for
    no reason a person could act on. What is here is what band 3 of the case workspace shows,
    plus the fingerprint planning itself watches, plus the version the recovery would write.
    """

    track_id: str
    track_state: str
    classification: str | None
    chosen_option_id: str | None
    to_version_id: str | None
    fingerprint: str | None


def plan_id(*, case_id: str, case_version: int, entries: Iterable[PlanEntry]) -> str:
    """The identity of one presented plan: a digest of the case and every track in it.

    Sorted by track id, so the identity does not depend on which query produced the rows --
    the read service orders by priority and the confirming transaction orders by id, and a
    plan whose identity changed with the ``ORDER BY`` would be a plan nobody could confirm.
    """
    ordered = sorted(entries, key=lambda entry: entry.track_id)
    body = {
        "v": PLAN_IDENTITY_VERSION,
        "case": case_id,
        "case_version": case_version,
        "tracks": [
            [
                entry.track_id,
                entry.track_state,
                entry.classification,
                entry.chosen_option_id,
                entry.to_version_id,
                entry.fingerprint,
            ]
            for entry in ordered
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

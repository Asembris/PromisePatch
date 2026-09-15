"""Union the per-shard duration slices a main run measured into one ``.test_durations``.

The backend suite is split across three runners by pytest-split, which decides where each
test goes by reading a committed file of measured per-test times. That file is a measurement,
so it goes stale: every test added after it was written is placed by an estimate rather than
by a number, and three shards that started balanced slowly stop being balanced. Staleness
costs balance and never coverage -- an unmeasured test is still collected and still run -- but
it is worth fixing, and fixing it by hand means running the whole suite on somebody's laptop.

So the shards measure themselves. On a push to main each one runs with ``--store-durations
--clean-durations``, which makes it write out *only* the tests it actually ran, and uploads
that slice. This unions the three slices back into a complete file for a person to commit.

The union refuses rather than resolves on an overlap. Two shards claiming the same test would
mean pytest-split had stopped partitioning the collection -- the thing that makes sharding
safe at all -- and picking one of the two numbers would leave that visible only as a slightly
odd duration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_SLICES = 3
"""The shard count in `.github/workflows/pr.yml`. Fewer means a shard failed to publish."""


def slices(directory: Path) -> list[Path]:
    """Every downloaded shard slice, in a stable order.

    ``actions/download-artifact`` with a pattern puts each artifact in its own subdirectory
    named after it, so the slices arrive as ``shards/test-durations-shard-N/.test_durations``.
    """
    return sorted(directory.glob("*/.test_durations"))


def union(paths: list[Path]) -> dict[str, float]:
    """Merge disjoint slices, refusing any test that two of them both claim."""
    merged: dict[str, float] = {}
    for path in paths:
        measured: dict[str, float] = json.loads(path.read_text(encoding="utf-8"))
        overlap = sorted(merged.keys() & measured.keys())
        if overlap:
            raise SystemExit(
                f"{path} overlaps an earlier slice on {len(overlap)} tests, so the shards are "
                f"no longer a partition of the suite; first is {overlap[0]}"
            )
        merged.update(measured)
    return merged


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: merge_test_durations.py SHARD_DIR OUTPUT", file=sys.stderr)
        return 2
    directory, output = Path(argv[1]), Path(argv[2])

    found = slices(directory)
    if len(found) != EXPECTED_SLICES:
        print(
            f"expected {EXPECTED_SLICES} shard slices under {directory}, found {len(found)}",
            file=sys.stderr,
        )
        return 1

    merged = union(found)
    output.write_text(json.dumps(merged, sort_keys=True, indent=4) + "\n", encoding="utf-8")
    print(f"{len(merged)} tests, {sum(merged.values()):.0f}s measured, written to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

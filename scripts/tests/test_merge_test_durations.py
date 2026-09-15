"""Unioning the shard slices is arithmetic over a partition, and refuses when it stops being one.

`scripts/merge_test_durations.py` exists so that the committed `.test_durations` -- the file
that decides which backend test runs on which of the three CI runners -- can be refreshed from
a real main run instead of from somebody's laptop. Each shard measures only the tests it ran
and publishes that slice; this puts the three back together.

The interesting case is the one that should never happen. Two shards claiming the same test
would mean pytest-split had stopped partitioning the collection, which is the property that
makes sharding safe at all -- and the merge would still produce a plausible file, differing
from the correct one only by a duration nobody would look at. So it refuses instead, and that
refusal is what is asserted here alongside the ordinary union.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.merge_test_durations import main, slices, union


def _slice(root: Path, group: int, measured: dict[str, float]) -> Path:
    """A downloaded artifact, laid out the way `actions/download-artifact` lays one out."""
    directory = root / f"test-durations-shard-{group}"
    directory.mkdir(parents=True)
    path = directory / ".test_durations"
    path.write_text(json.dumps(measured), encoding="utf-8")
    return path


def test_disjoint_slices_union_into_the_whole_suite(tmp_path: Path) -> None:
    _slice(tmp_path, 1, {"tests/test_a.py::one": 1.5})
    _slice(tmp_path, 2, {"tests/test_b.py::two": 2.5})
    _slice(tmp_path, 3, {"tests/test_c.py::three": 3.0})

    merged = union(slices(tmp_path))

    assert merged == {
        "tests/test_a.py::one": 1.5,
        "tests/test_b.py::two": 2.5,
        "tests/test_c.py::three": 3.0,
    }


def test_two_shards_claiming_one_test_refuses_rather_than_picking_a_number(
    tmp_path: Path,
) -> None:
    _slice(tmp_path, 1, {"tests/test_a.py::one": 1.5})
    _slice(tmp_path, 2, {"tests/test_a.py::one": 9.0})
    _slice(tmp_path, 3, {"tests/test_c.py::three": 3.0})

    with pytest.raises(SystemExit) as refusal:
        union(slices(tmp_path))

    assert "tests/test_a.py::one" in str(refusal.value)
    assert "partition" in str(refusal.value)


def test_a_missing_shard_fails_rather_than_writing_two_thirds_of_a_file(tmp_path: Path) -> None:
    """A shard that failed to publish would otherwise silently halve the durations file."""
    _slice(tmp_path, 1, {"tests/test_a.py::one": 1.5})
    _slice(tmp_path, 2, {"tests/test_b.py::two": 2.5})
    output = tmp_path / "out.json"

    assert main(["merge", str(tmp_path), str(output)]) == 1
    assert not output.exists()


def test_the_written_file_is_the_shape_pytest_split_reads_back(tmp_path: Path) -> None:
    _slice(tmp_path, 1, {"tests/test_b.py::two": 2.5})
    _slice(tmp_path, 2, {"tests/test_a.py::one": 1.5})
    _slice(tmp_path, 3, {"tests/test_c.py::three": 3.0})
    output = tmp_path / ".test_durations"

    assert main(["merge", str(tmp_path), str(output)]) == 0

    written = output.read_text(encoding="utf-8")
    assert json.loads(written) == {
        "tests/test_a.py::one": 1.5,
        "tests/test_b.py::two": 2.5,
        "tests/test_c.py::three": 3.0,
    }
    # Sorted and indented, so a refreshed file diffs against the committed one line by line
    # rather than as one unreadable row.
    assert written.startswith('{\n    "tests/test_a.py::one"')
    assert written.endswith("}\n")

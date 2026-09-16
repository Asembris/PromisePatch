"""The runnable example is executed, and every line it prints is asserted.

The example exists to show a stranger what the engine decides, so the thing worth protecting is
its **output**, not its internals. Asserting the whole transcript means a change to propagation,
option enumeration, the rule ladder or the classification order cannot quietly alter what the
example claims: it either prints this, or this test fails and somebody decides which is right.

The module is loaded from its path rather than imported by name, because `examples/` ships beside
the package rather than inside it --- a clean clone has the file, an installed wheel does not.
Nothing here starts a process, opens a socket or reads the clock.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "one_missing_delivery.py"

EXPECTED = """\
"today's raspberry delivery didn't arrive" -- maya, 07:00 on 04 March 2026
4 open promises read against the graph

UNAFFECTED         untouched by this exception  (1 of 4)
    EXT-4  Dev       R-UNREACH  NOT_REACHABLE

AUTO_RECOVERABLE   changed without asking anyone  (1 of 4)
    EXT-1  Amara     R-PREAPPROVED  PREAPPROVAL_COVERS

APPROVAL_REQUIRED  needs the customer to say yes  (1 of 4)
    EXT-2  Ben       R-VISIBLE-ASK  VISIBLE_CHANGE_ASK

BLOCKED            no permitted recovery; a person decides  (1 of 4)
    EXT-3  Chandra   R-NOSUB  NOSUB_CONSTRAINT

1 of 4 untouched: no message, no write, no reservation change, no hold.
Nothing above was carried out. The engine decided; acting on it is somebody else's job.
"""


@pytest.fixture(scope="module")
def example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("one_missing_delivery", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_example_file_is_where_the_readme_says_it_is() -> None:
    assert EXAMPLE.is_file()


def test_the_example_prints_exactly_this(
    example: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    example.main()
    assert capsys.readouterr().out == EXPECTED


def test_the_example_imports_nothing_but_the_engine_and_the_standard_library() -> None:
    """No backend, no database driver, no HTTP client, no cloud SDK.

    Read from the file's own syntax tree rather than from ``sys.modules``, which is process-wide
    and would pass or fail on what some other test happened to import.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(EXAMPLE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots == {"__future__", "datetime", "decimal", "typing", "promise_graph"}


def test_the_four_partitions_are_disjoint_and_cover_every_promise(example: ModuleType) -> None:
    """The counts the example prints are a partition, which is the claim the output makes."""
    settled = example.apply_exception_facts(example.SNAPSHOT, example.NOT_RECEIVED, example.NOW)
    analysis = example.analyze(settled.snapshot, example.NOT_RECEIVED, example.NOW)
    counted = [result.classification for result in analysis.classifications.values()]
    assert len(counted) == len(settled.snapshot.promises) == 4
    assert sorted(counted) == sorted(example.pg.Classification)

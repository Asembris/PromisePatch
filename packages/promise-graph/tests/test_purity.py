"""Machine-checked purity of the engine package.

import-linter enforces the module layering and a named forbidden list. This test enforces the
part import-linter cannot express: that the *only* things `promise_graph` imports are the
standard library and Pydantic, and that no module reads the clock, the environment, the
filesystem or a source of randomness.

It also enforces Proof H at the source level: no fixture identifier appears anywhere in the
engine, so no classification can branch on one.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import promise_graph
from tests.fixtures import hollow_oak as ho

SRC = Path(promise_graph.__file__).parent

FORBIDDEN_ROOTS = frozenset(
    {
        "asyncio",
        "logging",
        "os",
        "pathlib",
        "random",
        "socket",
        "subprocess",
        "urllib",
    }
)
"""Standard-library modules the engine must not reach for, even though they are stdlib."""

ALLOWED_ROOTS = (
    frozenset({"pydantic", "promise_graph"}) | set(sys.stdlib_module_names)
) - FORBIDDEN_ROOTS

FORBIDDEN_ATTRIBUTES = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "monotonic"),
    ("os", "getenv"),
    ("os", "environ"),
    ("random", "random"),
    ("uuid", "uuid1"),
    ("uuid", "uuid4"),
    ("Path", "read_text"),
    ("Path", "write_text"),
}
FORBIDDEN_NAMES = {"open", "eval", "exec", "input", "compile", "__import__", "hash"}


def modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(SRC.glob("*.py")):
        yield path.name, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


MODULES = list(modules())
MODULE_IDS = [name for name, _ in MODULES]


def test_the_engine_has_modules_to_check() -> None:
    assert len(MODULES) >= 10


@pytest.mark.parametrize(("name", "tree"), MODULES, ids=MODULE_IDS)
def test_only_stdlib_and_pydantic_are_imported(name: str, tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                continue
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        for root in roots:
            assert root in ALLOWED_ROOTS, f"{name} imports non-permitted module {root!r}"


@pytest.mark.parametrize(("name", "tree"), MODULES, ids=MODULE_IDS)
def test_no_clock_environment_filesystem_or_randomness(name: str, tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pair = (node.value.id, node.attr)
            assert pair not in FORBIDDEN_ATTRIBUTES, f"{name} uses {pair[0]}.{pair[1]}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_NAMES, f"{name} calls {node.func.id}()"


@pytest.mark.parametrize(("name", "tree"), MODULES, ids=MODULE_IDS)
def test_no_module_level_mutable_state(name: str, tree: ast.Module) -> None:
    """Module-level state would make results depend on call history.

    An immutable annotation (``Final``, ``Mapping``) is fine; ``__all__`` is metadata, not
    state, and is the only exempt name.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        if not isinstance(node.value, ast.Dict | ast.List | ast.Set):
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        assert isinstance(node, ast.AnnAssign), (
            f"{name} holds an un-annotated mutable module-level literal"
        )


def test_no_fixture_identifier_appears_in_the_engine() -> None:
    """Proof H at source level: classification cannot branch on a fixture id."""
    fixture_ids = {
        value
        for key, value in vars(ho).items()
        if key.isupper() and isinstance(value, str) and "-" in value
    }
    assert len(fixture_ids) > 20
    sources = {path.name: path.read_text(encoding="utf-8") for path in SRC.glob("*.py")}
    for identifier in fixture_ids:
        for module_name, source in sources.items():
            assert identifier not in source, f"{module_name} mentions fixture id {identifier!r}"


def test_no_utterance_text_appears_in_the_engine() -> None:
    """The raw utterance is provenance; nothing may key off its words."""
    sources = " ".join(path.read_text(encoding="utf-8") for path in SRC.glob("*.py"))
    for phrase in ("raspberry", "strawberr", "Valley Produce", "didn't arrive"):
        assert phrase not in sources


def test_package_ships_a_typing_marker() -> None:
    assert (SRC / "py.typed").exists()

"""``python -m evals`` -- validate the dataset, or run it offline and print what happened.

Three commands and no fourth. In particular there is **no live command**: nothing reachable
from here can construct a Bedrock client, so a machine with AWS credentials in its environment
and ``PP_LLM_PROVIDER=bedrock`` in its ``.env`` still cannot spend a cent by running an
evaluation. That is stronger than a flag defaulting to off, and it is the state this slice
deliberately ships in -- the live benchmark surface arrives with the run it is for, together
with the budget flags :mod:`evals.budget` already enforces.

It lives here rather than under ``pp`` because production must not import evaluation code, and
a subcommand on the operator CLI would be exactly that import.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.budget import EvalBudget, append_to_ledger
from evals.cases import EvalSplit
from evals.dataset import (
    DatasetError,
    GoldDataset,
    load_dataset,
    manifest_problems,
    validate_dataset,
    write_manifest,
)
from evals.report import render
from evals.runner import ScriptedAnswers, run_offline
from evals.summary import build_summary, ledger_entry

RESULTS_DIR = Path(".eval-results")
"""Where run artifacts land. Git-ignored: a run is a local fact about one machine."""


def _load() -> GoldDataset:
    return load_dataset()


def _validate(_: argparse.Namespace) -> int:
    dataset = _load()
    problems = [*validate_dataset(dataset), *manifest_problems(dataset, dataset.manifest())]
    manifest = dataset.manifest()
    print(f"{manifest.name} v{manifest.version}  {manifest.content_hash[:12]}")  # noqa: T201
    print(f"  cases     {manifest.cases}")  # noqa: T201
    print(f"  by job    {manifest.by_job}")  # noqa: T201
    print(f"  by split  {manifest.by_split}")  # noqa: T201
    if problems:
        print(f"\n{len(problems)} problem(s):")  # noqa: T201
        for problem in problems:
            print(f"  - {problem}")  # noqa: T201
        return 1
    print("\nThe dataset is internally consistent with production.")  # noqa: T201
    return 0


def _manifest(namespace: argparse.Namespace) -> int:
    dataset = _load()
    if namespace.write:
        manifest = write_manifest(dataset)
        print(f"wrote {manifest.name} v{manifest.version} {manifest.content_hash[:12]}")  # noqa: T201
        return 0
    print(dataset.manifest().model_dump_json(indent=2))  # noqa: T201
    return 0


async def _run(namespace: argparse.Namespace) -> int:
    dataset = _load()
    splits = None if not namespace.split else [EvalSplit(value) for value in namespace.split]
    selected = dataset.split(splits)
    answers = ScriptedAnswers.from_file()
    outcome = await run_offline(selected, answers, budget=EvalBudget(max_calls=namespace.max_calls))
    summary = build_summary(dataset, outcome, splits=splits)

    if namespace.json:
        print(json.dumps(summary.as_payload(), indent=2))  # noqa: T201
    else:
        print(render(summary))  # noqa: T201

    if namespace.out:
        directory = Path(namespace.out)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{summary.run_id}.json").write_text(
            json.dumps(summary.as_payload(), indent=2), encoding="utf-8"
        )
        append_to_ledger(directory / "cost-ledger.jsonl", ledger_entry(summary))
    return 0 if summary.gate_status == "pass" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="PromisePatch semantic evaluation. Offline; no provider is ever called.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="check the dataset against production")
    validate.set_defaults(handler=_validate)

    manifest = commands.add_parser("manifest", help="print or regenerate the dataset manifest")
    manifest.add_argument("--write", action="store_true", help="rewrite the committed manifest")
    manifest.set_defaults(handler=_manifest)

    replay = commands.add_parser(
        "replay", help="score the dataset from scripted answers and report"
    )
    replay.add_argument(
        "--split",
        action="append",
        choices=[split.value for split in EvalSplit],
        help="restrict to one split; repeatable. Omit for the whole dataset.",
    )
    replay.add_argument("--json", action="store_true", help="emit the machine-readable summary")
    replay.add_argument("--out", help="directory to write the summary and cost ledger into")
    replay.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help=(
            "refuse the run once this many provider calls have been made. Offline calls cost "
            "nothing; the cap is exercised on every run so it cannot rot before it is needed."
        ),
    )
    replay.set_defaults(handler=_run, is_async=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    try:
        if getattr(namespace, "is_async", False):
            import asyncio

            result: int = asyncio.run(namespace.handler(namespace))
            return result
        code: int = namespace.handler(namespace)
        return code
    except DatasetError as error:
        print(f"dataset error: {error}", file=sys.stderr)  # noqa: T201
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

# G8 curated DEVELOPMENT evidence

Date: **2026-09-26**. Repository HEAD `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5`; frozen release
candidate `4529a802e34e`. This page and its companion file are the curated, redacted public form
of every DEVELOPMENT evaluation result this repository holds locally. It answers G8's bullet
*"Curated redacted DEVELOPMENT evidence includes source commits, run IDs, hashes, limits and
scorer-correction provenance. Keep failed evidence and sealed holdouts."*

**Nothing was run to produce it.** No model, judge or provider was called, and no evaluation was
generated, resumed or rescored. Both holdouts stay sealed. The raw files were read and never written.

| | |
|---|---|
| Curated package | [`development-evidence/g8-development-evidence.v1.json`](development-evidence/g8-development-evidence.v1.json) |
| Its sha256 (committed LF bytes) | `bd86f3b54be5de19b5f033f7d7e2adc6567a719aa0ed910397cc6fafdb67f58a`, 174 726 bytes |
| Generator | reproduced byte-for-byte in the appendix; sha256 `aee15151d0d85f8bcf5fcefbe1085f0927ba96715a1f8b06f9a29aa0b8ed9eba` |
| Source | `.eval-results/`, git-ignored and local-only: **36 files**, left untouched |
| Determinism | generated twice, byte-identical; regenerated a third time after the 2026-09-26 host crash, byte-identical again |

On this machine `core.autocrlf` is `true`, so a working-tree checkout of the JSON may carry CRLF.
The hash is over the committed LF bytes:
`git show HEAD:docs/development-evidence/g8-development-evidence.v1.json | sha256sum`.

## 1. What the package contains, and what it omits

**Kept**, copied as recorded:

- every raw file's path, size and sha256;
- every run header's identity fields: run id, provider, model, region, commit, dataset
  name/version/hash, prompt and schema hashes, split, start time and pricing snapshot;
- each run's preflight ceilings, allowance and threshold policy;
- each run's cost-ledger lines;
- each run's summary as it was written at the time, including its gate status;
- per development case: id, job, tags, pass/fail, provider error, the harness's `reason` string,
  and the scorer's boolean metrics, with the customer gold and predicted labels;
- per explanation generation: family, source, failure, fact references and a word count;
- per judgement: the integer scores and boolean gates;
- totals summed from the same records.

**Omitted**, and named in the file's own `omitted` block:

| field | why |
|---|---|
| the model's raw structured reading per semantic case | every published aggregate is reproduced from the kept metrics and labels; the failing readings are described in the cited records |
| worker gold answers | committed in `evals/datasets`, identified here by dataset hash |
| explanation `speech` | unvalidated model prose whose completeness was `NOT ESTABLISHED`; bound by the file hash, word count kept |
| judge `brief_rationale` | prose from a judge the manual review discredited on one dimension; scores kept |
| per-case latency, tokens, cost and timestamps | operational, not evidential; per-run totals kept |
| repeated per-record identity blocks | the run header carries them once |
| summary result arrays and preflight bodies | restate the case records; identity, limits and gate status kept |

**Redaction is by omission only.** No kept value was altered. Before curation, all 36 raw files
were scanned for AWS access keys, OpenAI and NVIDIA keys, bearer tokens, ARNs, 12-digit account
numbers, request ids, email addresses, Windows user paths, Telegram bot tokens and private-key
headers. **Every file was clean.** The curated file was scanned again: zero hits, no `speech` field,
no rationale field, and the word `holdout` does not occur in it.

**No sealed material.** Every record in every raw file names the `development` split, and the
curated file's `splits_present` is `["development"]`. No holdout case was ever sent to a model:
47 semantic holdout cases and 14 explanation holdout cases, zero calls each. The gold datasets
(`evals/datasets/`) were already public and are not republished here.

## 2. Runs

Dataset `promisepatch-semantic-gold` v1.0.0, hash `9cf1ab78…44fd`, for every semantic and
challenger run. Dataset `promisepatch-explanation-gold` v1.0.0, hash `ebb9b679…7c57`, for every
explanation run. `answered` counts cases whose record holds a model reading.

| run id | model | commit | started (UTC) | cases / answered / passed | calls · attempts · est. USD (ledger) | as written | record |
|---|---|---|---|---|---|---|---|
| `a2470b4320e5` | Nova 2 Lite | `a70b55f166fb` | 09-07 17:58 | 22 / 14 / 21 | 14 · 14 · 0.0112463 | `fail`: unsafe rescue, stopped at case 22 | [semantic-benchmark.md](semantic-benchmark.md) |
| `36c1f008de80` | Nova 2 Lite | `d0eea2ff4051` | 09-07 19:42 | 58 / 50 / 49 | 50 · 50 · 0.0316512 | `fail`, under the pre-correction scorer | [semantic-benchmark-rerun.md](semantic-benchmark-rerun.md), [semantic-benchmark-scorer-audit.md](semantic-benchmark-scorer-audit.md) |
| `ceb14bb15b02` | Haiku 4.5 | `03c3723298b1` | 09-07 21:54 | 8 / 0 / 8, plus 3 provider failures | 3 · 3 · none | `fail`; zero readings | [challenger-harness-hardening.md](challenger-harness-hardening.md) |
| `8c78170b6bf4` | Haiku 4.5 | `7ef11cb4e0ab` | 09-07 22:03 | 0 answered, 3 provider failures | 3 · 3 · none | `fail`; zero readings | [challenger-harness-hardening.md](challenger-harness-hardening.md) |
| `10245bb11ec9` | Haiku 4.5 | `f1db47975586` | 09-08 12:47 | 0 answered, 3 provider failures | 3 · 3 · none | `pass` over zero readings, **vacuous** | on disk only; see §4 |
| `8e88336120d3` | GPT-4o-mini | `4886a9ba722f` | 09-08 14:40 | 0 answered, 3 authentication refusals | 3 · 3 · none | `pass` over zero readings, **vacuous** | [customer-intent-challenger-stage-a.md](customer-intent-challenger-stage-a.md) |
| `1dd2dba0d7f6` | GPT-4o-mini | `4886a9ba722f` | 09-08 16:22 | 12 / 12 / 8 | 12 · 12 · 0.00114675 | `fail`: 2 of 6 repairs, floor 3 | [customer-intent-challenger-stage-a.md](customer-intent-challenger-stage-a.md) |
| `6bbb247da030` | Nemotron 3 Super | `0401009e408e` | 09-08 17:51 | 12 / 12 / 6 | 12 · 12 · not modelled | `fail`: 0 of 6 repairs | [nemotron-challenger-stage-a.md](nemotron-challenger-stage-a.md) |
| `p48dev` | Nova 2 Lite | `a43adf8fb438` | 09-09 13:19 | 21 generations, 21 judgements | ledger 20 · 24 · 0.01521047; file 21 · 25 | `PLAN_SUMMARY` failed; the one repair spent | [explanation-quality-gate.md](explanation-quality-gate.md) |
| `p48dev-repaired` | Nova 2 Lite | `f4eacb88a1e9` | 09-09 15:30 | 1 bootstrap failure (`FALLBACK`) | 1 · 1 · none | not a run; bought nothing | [explanation-quality-gate.md](explanation-quality-gate.md) |
| `7172c7c894ae` | Nova 2 Lite | `a7bb57d03941` | 09-09 16:03 | 21 generations, 21 judgements | 21 · 26 · 0.01697905 | hard gates pass; manual review **fails** | [explanation-quality-gate.md](explanation-quality-gate.md) |

Every total above that the records also state agrees with them: Nova `36c1f008de80` at 50 calls
and $0.0316512; GPT-4o-mini at 8 of 12; Nemotron at 6 of 12, reproducing Nova's readings;
`p48dev` at 21 logical calls, 25 attempts, 35 214 input and 1 575 output tokens; and
`7172c7c894ae` at 21, 26, 37 835 and 1 634.

**`p48dev`'s ledger and run file disagree, and both are kept.** The ledger line says 20 calls and
24 attempts, while the file holds 21 generations with 25 attempts. The record explains it: the
canary was written before the ledger-on-exit fix, and the larger figure is recognised. Neither
line is rewritten.

## 3. Limits and budgets

All of these come from the run's own preflight, printed before its first call, except the P4.8
figures, which come from the gate's record.

| scope | ceiling | as applied |
|---|---|---|
| semantic benchmark, global across runs | 110 logical calls, 300 000 input and 30 000 output tokens, $0.20 | `a2470b4320e5` had the whole of it; `36c1f008de80` had 96 calls and $0.1887537 left |
| Haiku accidental run `ceb14bb15b02` | the same global ceiling | stopped by its failure policy at 3 |
| Haiku `8c78170b6bf4` | 30 calls, $0.15 | stopped at 3 |
| Stage A, Haiku `10245bb11ec9` | 12 calls, $0.03 | stopped at 3 |
| Stage A, GPT-4o-mini | 12 calls, $0.01 | `8e88336120d3` stopped at 3; `1dd2dba0d7f6` used 12 |
| Stage A, Nemotron | 12 calls, 100 000 input, 10 000 output, no dollar cap (`free_hosted_trial`) | used 12 |
| P4.8 explanation, per run | 21 logical calls, derived token ceilings, $0.07 | `p48dev` $0.0152 (ledger); `7172c7c894ae` $0.01698 |
| P4.8 explanation, DEVELOPMENT split | 2 runs, 42 calls, $0.14; a third identity refused | 2 runs bought, $0.03293092 |
| holdouts | each requires its own authorisation | **never granted; 0 calls** |

The threshold policy, fixed before any result was seen, is in each preflight and is copied into
the package: eight zero-tolerance safety gates and six quality thresholds for the semantic runs.

## 4. Scorer, harness and prompt corrections, in order

Each correction is dated against the evidence it affected. **No stored result was rewritten by any
of them.**

1. **Grounding fix, `7e4f36b`, 2026-09-07.** This was a product fix, not a scorer change.
   `a2470b4320e5` found an unsafe rescue, and the resolver was changed to fail closed on
   cross-kind evidence. The run stayed as recorded, in `historical-a2470b4320e5/`, and
   `36c1f008de80` is a fresh run from case 1.
2. **Scorer correction, `60316a8`, recorded at `03c3723`, 2026-09-07.** `out_of_scope_declined`
   had measured the model's self-label, and it now measures the engine's refusal (§16.3).
   `36c1f008de80` was rescored from its stored answers with zero provider calls:
   - **Safety:** 2 of 2 declined.
   - **Quality:** still failing, on terse-assent recall 2/5 and indirect-refusal recall 3/4.

   Model outputs were captured under `d0eea2ff…`. **The stored summary was not regenerated:** it
   still reads `fail`, generated `2026-09-07T19:42:56Z` under the pre-correction scorer. The
   authoritative verdict is the audit page's.
3. **Harness hardening, 2026-09-07/08.** A pytest line became a live run (`ceb14bb15b02`), and
   provider failures had been labelled as quality results. After the hardening:
   - spend is phrase-authorised per scope;
   - a test process cannot build a paid provider;
   - provider failures are a state of their own;
   - Stage A has its own ceiling (`f1db479`).

   The three Haiku attempts obtained **zero** readings, and AWS refused each one before the model
   (`INVALID_PAYMENT_INSTRUMENT`). **Haiku quality was never measured.**
4. **Challenger replacement, 2026-09-08.** Haiku was replaced by GPT-4o-mini, and then Nemotron was
   run as the third challenger. The scorer, selection, prompt and thresholds were unchanged.
5. **P4.8 prompt repair, `7bbfd5b`, 2026-09-09.** This was the one permitted repair: a
   `PROMPT_DEFECT` found in `p48dev`. The prompt hash moved, so `p48dev` cannot be rejudged, and
   DEVELOPMENT was generated again as `7172c7c894ae`.
6. **Judge finding, 2026-09-09, with no scorer change.** Nemotron scored causal completeness 5 on
   nine passages that omit a required fact. The finding is `JUDGE_DEFECT` on one dimension, and
   causal completeness is `NOT ESTABLISHED`. P4.8 closed by selecting the deterministic renderer.

## 5. Failed evidence, preserved

Nothing that failed was removed or relabelled:

- the unsafe-rescue run `a2470b4320e5`;
- the pre-correction `fail` summary of `36c1f008de80`;
- the nine failing Nova development cases;
- all four zero-reading attempts, with their provider-failure logs;
- GPT-4o-mini's four misses;
- Nemotron's six;
- `p48dev`'s `PLAN_SUMMARY` failure;
- `p48dev-repaired`'s bootstrap record;
- `7172c7c894ae`'s failed manual review.

Every one is in the package with its file hash.

**Two summaries read `pass` and must not be quoted as results.** `10245bb11ec9` and `8e88336120d3`
show `gate_status: pass` with 3 unscored cases and 0 readings. That is safety gates passing
vacuously over nothing. `10245bb11ec9` is not cited by run id in any earlier record. It is the
second intended Haiku Stage A, at `f1db479`, and it is one of the attempts
[challenger-harness-hardening.md](challenger-harness-hardening.md) describes as *"refused by the
AWS data plane before the model was reached"*.

## 6. Provenance checks made here

- **The challenged source still matches.** Both challenger records cite a Nova source-results
  sha256 of `c8046dcf…9b55`. That digest is canonical JSON over the 30 customer development
  results (`evals/challenger.py`, `SourceRun.results_sha`), not a file hash. It was recomputed
  from today's `development-us.amazon.nova-2-lite-v1_0.jsonl` (file sha256 `3485969a…73ae`) and
  **matches exactly**.
- **The Stage-A selection was re-derived and matches.** `select_stage_a`, algorithm v1, was run
  over Nova's stored answers and the committed dataset, read-only. It gives six pairs, and these
  match all of the following:
  - all three `challenger-set-*.json` files;
  - the twelve case ids in the GPT-4o-mini run file;
  - the twelve in the Nemotron run file.
- **Two selection files were rewritten after their runs.** Found here and recorded, not repaired:
  - `challenger-set-gpt-4o-mini-2024-07-18.json` and the Haiku set carry
    `recorded_at 2026-09-22T20:13:5xZ` and `git_sha 4d1f4a3…`, two weeks after their runs.
  - The GPT-4o-mini file now names `source_run_id: source000001` and `source_results_sha
    ccdc880c…`. That run id is a fixture in `scripts/tests/test_openai_challenger.py` and
    `scripts/tests/test_spend_interlock.py`.
  - Both tests point `RESULTS_DIR` at `tmp_path` in the code as it stands. **What wrote the real
    directory is not established here.**
  - The pairs are unchanged. The run files and the re-derivation agree, so no measured result
    depends on the rewritten header.
  - The Nemotron set is the original, `recorded_at 2026-09-08T17:51:48Z`.
- **Judge calls: the record says 21, the files say 42.**
  [explanation-quality-gate.md](explanation-quality-gate.md), *What this gate spent*, lists
  `NVIDIA JUDGE CALLS 21 (7172c7c894ae)`. But `explanation-p48dev.jsonl` also holds 21 Nemotron
  judge records (`nvidia/nemotron-3-super-120b-a12b`, all `SCORED`, one logical call each, from
  `2026-09-09T13:21:21Z`). That is consistent with the same page's statement that `p48dev` passed
  six of seven families. Nemotron's development judging on disk is therefore **42 logical calls**,
  on `free_hosted_trial`, with no USD modelled. The historical page is not edited.
- **File count.** The directory holds 36 files, including 11 under three `historical-*`
  subdirectories. [g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) row 9 wrote "28 files"
  without stating how it counted. The difference is not reconciled.

## 7. What this does not claim

- It does not claim a model passed. No DEVELOPMENT run on this page met every gate, and the
  shipped explanation path is the deterministic renderer.
- It does not claim the raw files are public. They stay local. Anyone holding them can check them
  against the hashes, and nobody else can.
- It makes no claim about a holdout. None was opened.

## Appendix — the generator

sha256 `aee15151d0d85f8bcf5fcefbe1085f0927ba96715a1f8b06f9a29aa0b8ed9eba`, over the bytes between
the fences, with LF line endings and a final newline. It is run from the repository root as
`python curate_development_evidence.py <output.json>`. It needs only the standard library, calls
nothing and writes only its output path.

```python
"""Curate the local DEVELOPMENT evaluation results into one public, redacted evidence file.

Read-only over `.eval-results/` (git-ignored, local-only). Writes one JSON document to the path
given as the only argument. Calls no model, opens no network connection, reads no environment
and never writes inside `.eval-results/`. Redaction is by omission: every value it keeps is
copied as recorded, and every field it drops is named in `omitted`.
"""

import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(".eval-results")

RUNS = {
    "a2470b4320e5": ("semantic", "Nova 2 Lite DEVELOPMENT, first run, stopped at case 22 by the unsafe-rescue gate", "docs/semantic-benchmark.md"),
    "36c1f008de80": ("semantic", "Nova 2 Lite DEVELOPMENT, complete rerun after the grounding fix; rescored by the scorer correction", "docs/semantic-benchmark-rerun.md; docs/semantic-benchmark-scorer-audit.md"),
    "ceb14bb15b02": ("semantic", "Haiku 4.5 DEVELOPMENT, accidental live run started by pytest; zero readings", "docs/challenger-harness-hardening.md"),
    "8c78170b6bf4": ("challenger", "Haiku 4.5 Stage A, intended; zero readings (AWS refused before the model)", "docs/challenger-harness-hardening.md"),
    "10245bb11ec9": ("challenger", "Haiku 4.5 Stage A, later attempt; zero readings (AWS refused before the model)", "docs/challenger-harness-hardening.md (not cited there by run id)"),
    "8e88336120d3": ("challenger", "GPT-4o-mini Stage A, header-only; zero readings (authentication refused)", "docs/customer-intent-challenger-stage-a.md"),
    "1dd2dba0d7f6": ("challenger", "GPT-4o-mini Stage A, 12 readings", "docs/customer-intent-challenger-stage-a.md"),
    "6bbb247da030": ("challenger", "Nemotron 3 Super Stage A, 12 readings", "docs/nemotron-challenger-stage-a.md"),
    "p48dev": ("explanation", "P4.8 explanation DEVELOPMENT, original run (before the one prompt repair)", "docs/explanation-quality-gate.md"),
    "p48dev-repaired": ("explanation", "P4.8 bootstrap record; bought nothing and is not a run", "docs/explanation-quality-gate.md"),
    "7172c7c894ae": ("explanation", "P4.8 explanation DEVELOPMENT, repaired rerun", "docs/explanation-quality-gate.md"),
}

HEADER_FIELDS = (
    "run_id", "kind", "mode", "provider", "model_id", "region", "git_sha", "dataset_name",
    "dataset_version", "dataset_hash", "splits", "started_at", "pricing_snapshot", "prompts",
    "prompt_system_hash", "schema_hash", "endpoint", "decoding",
)
CASE_FIELDS = ("case_id", "job", "split", "tags", "passed", "provider_error", "error_category", "reason", "metrics")
FAILURE_FIELDS = ("case_id", "job", "split", "attempt", "category")
GENERATION_FIELDS = ("case_id", "split", "source", "failure", "fact_refs")
JUDGE_FIELDS = ("case_id", "family", "split", "outcome")
SUMMARY_FIELDS = ("run_id", "generated_at", "git_sha", "mode", "model_id", "splits", "cases", "passed", "failed", "gate_status")

OMITTED = [
    {"field": "case.observed (semantic and challenger runs)", "why": "the model's raw structured reading per case; every published aggregate is reproduced from the kept boolean metrics and labels, and the failing readings are described in the cited records"},
    {"field": "case.expected (semantic and challenger runs)", "why": "the gold answer is committed in evals/datasets and is identified here by dataset hash; customer gold and predicted labels are kept inside metrics"},
    {"field": "generation.speech (explanation runs)", "why": "unvalidated model prose; its completeness was NOT ESTABLISHED and its content is bound by the file sha256; the word count is kept"},
    {"field": "judge.verdict.brief_rationale (explanation runs)", "why": "unvalidated judge prose from a judge the manual review discredited on causal completeness; the integer scores and boolean gates are kept"},
    {"field": "per-case latency, token usage, estimated_usd and timestamps", "why": "operational, not evidential; per-run totals are kept, summed from the same records"},
    {"field": "generation.identity and judge.identity per record", "why": "repeats the run header; the header, the judge identity and the per-case generation fingerprint length are kept once per run"},
    {"field": "run summary .json results arrays and preflight .txt bodies", "why": "restate the case records; identity, ceilings, allowance and gate status are kept"},
]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_id_of(path):
    name = path.name
    for run_id in sorted(RUNS, key=len, reverse=True):
        if name.startswith(run_id) or path.parent.name == f"historical-{run_id}":
            return run_id
    if name.endswith(".jsonl") and not name.endswith("ledger.jsonl"):
        first = records(path)[0]
        return first.get("run_id")
    return None


def preflight(path):
    text = path.read_text(encoding="utf-8")
    out = {}
    for block in ("CEILINGS", "ALLOWANCE FOR THIS RUN", "THIS RUN"):
        match = re.search(r"^  " + re.escape(block) + r"[^\n]*\n((?:    [^\n]*\n)+)", text, re.M)
        if match:
            out[block.lower()] = {
                re.split(r"\s{2,}", line.strip(), maxsplit=1)[0]: (re.split(r"\s{2,}", line.strip(), maxsplit=1) + [""])[1]
                for line in match.group(1).splitlines()
            }
    out["thresholds"] = re.findall(r"^    ((?:safety|quality)\s+.+?)\s*$", text, re.M)
    return out


def total(rows, field):
    values = [r.get(field) for r in rows if r.get(field) is not None]
    if not values:
        return None
    return str(sum(Decimal(str(v)) for v in values)) if field == "estimated_usd" else sum(values)


def main(out_path):
    files = sorted((p for p in ROOT.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
    raw = [{"path": p.as_posix(), "sha256": sha256(p), "bytes": p.stat().st_size, "run_id": run_id_of(p)} for p in files]

    ledgers = {}
    for name in ("cost-ledger.jsonl", "explanation-cost-ledger.jsonl"):
        for line in records(ROOT / name):
            if "run_id" in line and "calls" in line:
                ledgers.setdefault(line["run_id"], []).append(
                    {k: line.get(k) for k in ("provider", "model_id", "git_sha", "calls", "attempts", "input_tokens", "output_tokens", "estimated_usd", "recorded_at")} | {"ledger": name})

    runs = []
    for run_id, (suite, role, record) in RUNS.items():
        mine = [p for p in files if run_id_of(p) == run_id]
        run = {"run_id": run_id, "suite": suite, "role": role, "record": record, "files": [p.as_posix() for p in mine], "ledger": ledgers.get(run_id, [])}
        cases, failures, generations, judges = [], [], [], []
        for p in mine:
            if p.suffix == ".txt":
                run["preflight"] = preflight(p)
            elif p.suffix == ".json" and "challenger-set" not in p.name:
                summary = json.loads(p.read_text(encoding="utf-8"))
                run["summary_as_written"] = {k: summary.get(k) for k in SUMMARY_FIELDS if k in summary}
                ops = summary.get("operations") or {}
                run["summary_as_written"]["operations"] = {k: ops.get(k) for k in ("calls", "attempts", "provider_failures", "unscored_cases", "reused_cases", "stopped")}
            elif p.suffix == ".jsonl":
                for r in records(p):
                    kind = r.get("kind")
                    if kind in ("run", "explanation_run"):
                        run["header"] = {k: r[k] for k in HEADER_FIELDS if k in r}
                    elif kind == "case":
                        cases.append(r)
                    elif kind == "provider_failure":
                        failures.append(r)
                    elif kind == "generation":
                        generations.append(r)
                    elif kind == "judge":
                        judges.append(r)
        if cases:
            run["totals"] = {
                "cases": len(cases),
                "passed": sum(1 for c in cases if c.get("passed")),
                "failed": sum(1 for c in cases if not c.get("passed")),
                "provider_error": sum(1 for c in cases if c.get("provider_error")),
                "model_answered": sum(1 for c in cases if c.get("observed")),
                "attempts": total(cases, "attempts"),
                "input_tokens": total(cases, "input_tokens"),
                "output_tokens": total(cases, "output_tokens"),
                "estimated_usd": total(cases, "estimated_usd"),
            }
            run["cases"] = [{k: c.get(k) for k in CASE_FIELDS} for c in sorted(cases, key=lambda c: c["case_id"])]
        if failures:
            run["provider_failures"] = [{k: f.get(k) for k in FAILURE_FIELDS} for f in failures]
        if generations:
            usage = [g.get("usage") or {} for g in generations]
            run["generation_totals"] = {
                "records": len(generations),
                "by_source": {s: sum(1 for g in generations if g.get("source") == s) for s in sorted({str(g.get("source")) for g in generations})},
                "failures": sum(1 for g in generations if g.get("failure")),
                "logical_calls": sum(u.get("logical_calls") or 0 for u in usage),
                "provider_attempts": sum(u.get("provider_attempts") or 0 for u in usage),
                "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
                "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
            }
            run["generations"] = [
                {k: g.get(k) for k in GENERATION_FIELDS} | {"family": (g.get("identity") or {}).get("family"), "speech_words": len((g.get("speech") or "").split())}
                for g in sorted(generations, key=lambda g: (g.get("identity") or {}).get("case_id") or "")
            ]
            for g, row in zip(sorted(generations, key=lambda g: (g.get("identity") or {}).get("case_id") or ""), run["generations"]):
                row["case_id"] = row["case_id"] or (g.get("identity") or {}).get("case_id")
        if judges:
            ident = judges[0].get("identity") or {}
            run["judge"] = {k: ident.get(k) for k in ("judge_provider", "judge_model_id", "judge_prompt_hash", "rubric_version", "verdict_schema_hash")}
            run["judgements"] = [
                {k: j.get(k) for k in JUDGE_FIELDS} | {k: v for k, v in (j.get("verdict") or {}).items() if k != "brief_rationale"}
                for j in sorted(judges, key=lambda j: j.get("case_id") or "")
            ]
        runs.append(run)

    sets = []
    for p in files:
        if p.name.startswith("challenger-set-"):
            s = json.loads(p.read_text(encoding="utf-8"))
            sets.append({"path": p.as_posix()} | {k: s.get(k) for k in ("algorithm_version", "challenger_model_id", "source_run_id", "source_results_sha", "git_sha", "recorded_at", "failure_case_ids", "control_case_ids")})

    splits = sorted({str(c.get("split")) for r in runs for c in r.get("cases", []) + r.get("provider_failures", []) + r.get("generations", []) + r.get("judgements", [])})

    document = {
        "package": "promisepatch-g8-development-evidence",
        "version": "1.0.0",
        "source": ".eval-results/ (git-ignored, local-only; read, never written)",
        "splits_present": splits,
        "raw_files": raw,
        "runs": runs,
        "challenger_selection_files": sets,
        "omitted": OMITTED,
    }
    Path(out_path).write_text(json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(sys.argv[1])
```

# G8 contribution provenance

Date: **2026-09-26**. This page answers G8's *"contribution provenance within window"* from two
sources only: the repository's git history at `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5`, and
GitHub's public repository metadata, read unauthenticated today. It makes no claim either source
cannot support.

## 1. The window

From `new_roadmap.md` §2, the frozen local-only plan, which quotes the official rules:

| | |
|---|---|
| submission opens | **2026-08-31 17:15 UTC** |
| submission deadline | **2026-10-23 19:00 UTC** |

## 2. What the sources say

| fact | value | source |
|---|---|---|
| repository | `Asembris/PromisePatch`, `public`, not a fork, default branch `main` | GitHub REST `GET /repos/Asembris/PromisePatch` |
| license | `Apache-2.0`, detected by GitHub; `LICENSE` at the root since the first commit | GitHub REST; `git show --stat 1799971` |
| **repository created** | **2026-09-02 15:40:04 UTC**, server-side | GitHub REST `created_at` |
| last push | 2026-09-24 21:54:13 UTC | GitHub REST `pushed_at` |
| **root commit** | **`1799971`**, *"chore: workspace foundation"*, author and committer date `2026-09-02T22:25:53+02:00` (20:25:53 UTC) | `git rev-list --max-parents=0 HEAD` |
| root commits | exactly one | the same |
| commits to HEAD | **783**, no merges | `git rev-list --count HEAD`, `--merges` |
| author dates | earliest `2026-09-02T22:25:53+02:00`, latest `2026-09-24T23:53:03+02:00` | `git log --format=%aI` |
| committer dates | earliest `2026-09-02T22:25:53+02:00` | `git log --format=%cI` |
| days with commits | 23, from 2026-09-02 to 2026-09-24 | `git log --date=short` |
| author and committer identity | one identity on all 783 commits, `Asembris` | `git log --format='%an'` / `'%cn'` |
| `Co-Authored-By` trailers | **14 commits**, each naming *Claude Opus 5*, dated 2026-09-09 to 2026-09-12 | `git log --format='%(trailers:key=Co-Authored-By)'` |
| engine package history | 17 commits touch `packages/promise-graph/`, from `1799971` to `e84e7dd` (2026-09-16) | `git rev-list --count HEAD -- packages/promise-graph` |

**Every commit's author and committer date falls inside the window.** The earliest is 2 days
3 hours after the window opened, and the latest is 28 days 21 hours before it closes. The repository was
created inside the window as well, 4 h 46 min before the root commit.

## 3. What the sources cannot say

- **A commit date is not a writing date.** Git records when a change was committed, and the
  committer sets that date locally. The server-side `created_at` corroborates that the repository
  did not exist on GitHub before 2026-09-02. It says nothing about when files were first written
  on a local disk.
- **The first engine code was committed in one 33-second burst.** Between `22:25:53` and
  `22:26:26` on 2026-09-02 (local time), ten commits landed:
  - the scaffolding, `1799971`, 11 files and 1 060 lines, with a 5-line engine `__init__`;
  - a CI gate;
  - six `feat(engine)` commits, 6 931 lines between them;
  - the engine's fixtures and property tests, 1 789 lines;
  - ADRs 0001–0006.

  They add 10 132 lines in all. Code of that size was written before it was committed, and git
  cannot show when. **This page does not claim it was written inside the window, and does not
  claim it was written before.** It claims only what the dates show.
- **Authorship.** Git carries one author identity. Fourteen commit messages record Claude Opus 5 as
  co-author through a trailer, and the repository has carried a `CLAUDE.md` operating contract for
  AI-assisted sessions since its root commit. Beyond those trailers, git has no field that would say which lines a person wrote
  and which an assistant proposed. **No sole-authorship and no originality claim is made here.**
- **No upstream endorsement.** The engine is published inside this monorepo, and no package
  registry release or maintainer endorsement is claimed.

## 4. Verdict for the row

G8 row 12, *"contribution provenance within window"*, is **CLOSED** as a written record: the
repository, its root commit and every one of its 783 commits are dated inside the submission
window, and the limits in §3 are stated beside that. Any later commit extends the history, and the
freeze session should restate the commit count at the release SHA.

# Trycycle Runtime Feasibility for Atelier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Produce a repo-owned feasibility and architecture package that
determines which trycycle-style planner/worker hardening behaviors can be
adapted into Atelier `runtime profile`s, which cannot, and what architectural
changes would be required without changing Atelier's core functional intent.

**Architecture:** This slice is analysis and contract writing, not product
surface implementation. Baseline Atelier's current planner/worker contracts,
compare them against the trycycle-derived behaviors named by the user and the
`trycycle-planning` skill, then publish a clear verdict: direct adaptation is
not currently feasible as a full runtime-profile substitution, but a smaller
repo-owned hardening profile is feasible. Record the mismatches, the adoptable
subset, and the architectural changes that would be needed for anything closer
to trycycle's subagent-heavy model.

**Tech Stack:** Markdown design docs, pytest doc-contract tests, existing
Atelier planner/worker templates, skills, runtime/session modules.

---

## Execution prerequisites

- Run `bash .githooks/worktree-bootstrap.sh` in this worktree before the first
  code change so repo-local hooks are bootstrapped here as required by
  `AGENTS.md`.
- Treat the user clarifications in the planning transcript and the
  `trycycle-planning` skill as the only trycycle source material in this slice.
  Do not invent external trycycle guarantees or depend on a local trycycle
  install.
- Do not modify `atelier plan`, `atelier work`, config models, session routing,
  or runtime-launch code in this slice. The outcome here is a repo-owned
  decision package, not a shipped runtime-profile feature.
- Use `runtime profile` as the canonical term throughout the new doc and tests.
  Reserve `contract` for statements of guarantees inside that doc.
- Keep these user decisions fixed:
  - repo-owned source of truth only
  - shared workspace identifiers stay stable
  - hybrid verification floor for any later feature work
  - it is acceptable to conclude that direct trycycle adaptation is not
    currently feasible
- Before writing the new doc, read these sources and anchor the analysis in
  them:
  - `docs/behavior.md`
  - `docs/dogfood.md`
  - `docs/worker-runtime-architecture.md`
  - `docs/north-star-review-gate.md`
  - `src/atelier/templates/AGENTS.planner.md.tmpl`
  - `src/atelier/templates/AGENTS.worker.md.tmpl`
  - `src/atelier/commands/plan.py`
  - `src/atelier/commands/work.py`
  - `src/atelier/worker/prompts.py`
  - `src/atelier/skills.py`
  - `src/atelier/skills/planner-startup-check/SKILL.md`
  - `src/atelier/skills/startup-contract/SKILL.md`
  - `src/atelier/skills/plan-changesets/SKILL.md`
  - `src/atelier/skills/publish/SKILL.md`

## User-visible outcome

- Add a repo-owned design document that answers whether trycycle-like planner
  and worker hardening can fit Atelier's current orchestration model.
- The document must explain the mismatches between trycycle and Atelier,
  including subagent communication, durable Beads/message coordination,
  multiple concurrent workers, PR-driven late phases, review-sized changesets,
  and operator accountability.
- The document must state a concrete verdict:
  - full trycycle-style runtime substitution is not currently feasible without
    deeper architectural change
  - a smaller repo-owned `runtime profile` cut is feasible for planner and
    worker hardening guidance
- The document must describe what would have to change in Atelier to support
  deeper trycycle-style execution hardening while preserving Atelier's core
  featureset.
- Add a doc-contract test so this analysis remains durable and does not drift
  later.

## Contracts and invariants

- The analysis must preserve Atelier's functional intent:
  orchestrated agent development with operator accountability.
- The document must explicitly keep these Atelier invariants in view:
  - durable planning state lives in Beads
  - planner and worker communicate through durable tickets/messages plus
    external signals, not ephemeral subagent chat
  - workers may run concurrently against available work
  - PR review, publish/finalize, and merge-state handling are part of the
    worker lifecycle in PR-enabled projects
  - changesets must stay human-reviewable and may be split when they grow too
    large
- The analysis must not collapse agent transport, runtime profile, and
  orchestration architecture into the same concept.
- If the analysis recommends a future runtime profile, it must be repo-owned and
  layered onto existing agent CLIs. It must not depend on a local trycycle
  installation or a new `AgentSpec`.
- If the analysis finds a deeper mismatch, the document must explain how Atelier
  could change its architecture without changing its core intent or operator
  accountability model.

## Non-goals

- Do not add `--runtime` flags.
- Do not add `agent.runtime` config.
- Do not alter planner session targeting or worker prompt wiring.
- Do not add a `trycycle` binary dependency.
- Do not claim that trycycle can be embedded directly unless the code/docs
  materially support that conclusion. The expected conclusion for this slice is
  narrower: partial adaptation is feasible, direct substitution is not.
- Do not update `docs/behavior.md` or `README.md` to describe a feature that
  does not exist yet.

## File structure

- Create: `docs/trycycle-runtime-feasibility.md`
  Responsibility: repo-owned decision document describing Atelier's current
  planner/worker model, the trycycle-derived behaviors under review, the
  mismatch matrix, the feasibility verdict, the recommended runtime-profile
  cut, the required architectural changes for deeper adaptation, and the future
  verification floor.
- Create: `tests/atelier/test_trycycle_runtime_feasibility.py`
  Responsibility: keep the feasibility document stable by asserting that the
  required sections and core terms remain present.

## Strategy gate

The wrong plan would ship a user-facing `trycycle` runtime profile first and
only then ask whether that profile actually fits Atelier's orchestration model.
That would optimize for a CLI/config surface instead of the user's real goal.

The second wrong plan would reduce trycycle to a few extra prompt lines in
`AGENTS.md`. The user explicitly called out trycycle's harder planning,
verification, and implementation feedback loops plus its use of subagent
communication. A prompt addendum alone does not answer whether that model can
fit Atelier.

The third wrong plan would ignore Atelier's functional intent. Atelier is not
just a prompt runner. It is an orchestration system with durable Beads state,
multiple workers, operator approval points, PR-driven late phases, and
review-sized changeset constraints. Any recommendation that ignores those
properties would be wrong even if it sounded "trycycle-like."

The clean cut for this slice is:

- publish one repo-owned feasibility document
- keep the conclusion evidence-backed and explicit
- state that direct trycycle-style runtime substitution is not currently
  feasible in Atelier's present architecture
- identify the smaller hardening behaviors that *are* compatible with a future
  repo-owned `runtime profile`
- explain the architectural changes needed to go further without changing
  Atelier's core functional intent

That lands the user's requested end state directly and avoids premature product
surface work.

### Task 1: Create the feasibility document scaffold and lock its required shape

**Files:**
- Create: `docs/trycycle-runtime-feasibility.md`
- Create: `tests/atelier/test_trycycle_runtime_feasibility.py`

- [ ] **Step 1: Identify or write the failing test**

Read the prerequisite source files first, then add a doc-contract test that
defines the minimum structure of the new document.

```python
from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "trycycle-runtime-feasibility.md"


def test_trycycle_runtime_feasibility_doc_exists() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "# Trycycle Runtime Feasibility for Atelier" in content
    assert "## Scope" in content
    assert "## Source Inputs" in content
    assert "## Atelier Invariants" in content
    assert "## Trycycle-Derived Behaviors Under Review" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: FAIL because the feasibility doc and its required sections do not
exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `docs/trycycle-runtime-feasibility.md` with these top-level sections and
brief initial prose in each:

- `# Trycycle Runtime Feasibility for Atelier`
- `## Scope`
- `## Source Inputs`
- `## Atelier Invariants`
- `## Trycycle-Derived Behaviors Under Review`

In `## Scope`, say explicitly that this slice determines feasibility and future
architecture rather than shipping a runtime-profile feature.

In `## Source Inputs`, state that the analysis is based on:

- the user transcript in this planning thread
- the `trycycle-planning` skill
- the existing Atelier planner/worker templates, docs, and runtime code

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Tighten section wording, keep prose lines at 80 chars, and use
`runtime profile` consistently.

Run:

```bash
just format
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/trycycle-runtime-feasibility.md \
  tests/atelier/test_trycycle_runtime_feasibility.py
git commit -m "docs(runtime): add trycycle feasibility scaffold" \
  -m "- add a repo-owned feasibility document for trycycle-style adaptation" \
  -m "- add a doc-contract test that locks the required analysis sections" \
  -m "- keep this slice analysis-only instead of shipping a runtime surface"
```

### Task 2: Record the Atelier baseline and the real mismatch matrix

**Files:**
- Modify: `docs/trycycle-runtime-feasibility.md`
- Modify: `tests/atelier/test_trycycle_runtime_feasibility.py`

- [ ] **Step 1: Identify or write the failing test**

Extend the doc-contract test so it requires the operational details that matter
for this decision.

```python
def test_trycycle_runtime_feasibility_doc_captures_critical_mismatches() -> None:
    content = DOC_PATH.read_text(encoding="utf-8").lower()
    assert "shared message/ticket space" in content
    assert "subagent" in content
    assert "multiple workers" in content
    assert "operator accountability" in content
    assert "pull request" in content or "pr-driven" in content
    assert "human cognitive review load" in content
    assert "## mismatch matrix" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: FAIL because the doc does not yet capture Atelier's real constraints
or the mismatch matrix.

- [ ] **Step 3: Write minimal implementation**

Fill the document with evidence-backed analysis from the prerequisite sources.

In `## Atelier Invariants`, document:

- planner uses Beads as the durable planning source of truth
- worker execution is one-changeset-per-session
- planner/worker coordination is durable and thread-based, not ephemeral
- workers may run concurrently
- worker completion includes publish/PR/review lifecycle handling
- oversized work must be split to preserve reviewability

Add `## Mismatch Matrix` and compare, at minimum, these concerns:

- planner hardening and revision loops
- worker verification and self-review loops
- subagent communication versus durable Beads/messages
- concurrent workers versus session-local orchestration
- PR-driven late phases versus prompt-completion-oriented execution
- automatic changeset splitting to preserve human review load
- operator accountability versus autonomous local subagent convergence

For each row, state one of:

- `Compatible now as runtime-profile guidance`
- `Compatible only with bounded adaptation`
- `Not compatible without architectural change`

Also add a short `## Observed Strengths Already Present in Atelier` section so
the document is not framed as "Atelier has none of this today." Include items
such as:

- planner startup discipline
- worker north-star review loop
- publish/finalize gating
- changeset splitting expectations

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Make the mismatch matrix crisp and non-redundant. Every claim should trace back
to the user request or an Atelier source file already listed in the
prerequisites.

Run:

```bash
just format
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/trycycle-runtime-feasibility.md \
  tests/atelier/test_trycycle_runtime_feasibility.py
git commit -m "docs(runtime): map trycycle mismatches against atelier" \
  -m "- record the current Atelier planner and worker invariants" \
  -m "- add a mismatch matrix for subagents, durable messaging, PR flow, and review load" \
  -m "- distinguish existing Atelier strengths from deeper trycycle-only assumptions"
```

### Task 3: Publish the verdict and the future implementation shape

**Files:**
- Modify: `docs/trycycle-runtime-feasibility.md`
- Modify: `tests/atelier/test_trycycle_runtime_feasibility.py`

- [ ] **Step 1: Identify or write the failing test**

Extend the doc-contract test so it requires the decision and the recommended
future cut.

```python
def test_trycycle_runtime_feasibility_doc_records_verdict_and_follow_up_shape() -> None:
    content = DOC_PATH.read_text(encoding="utf-8").lower()
    assert "## feasibility verdict" in content
    assert "## recommended runtime profile cut" in content
    assert "## required architectural changes" in content
    assert "## future verification floor" in content
    assert "repo-owned" in content
    assert "runtime profile" in content
    assert "not currently feasible" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: FAIL because the verdict and future-shape sections do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add the final decision sections to the document and make the verdict explicit.

Write `## Feasibility Verdict` to say:

- direct trycycle-style runtime substitution is not currently feasible in
  Atelier's present architecture
- the deepest mismatch is trycycle's reliance on subagent communication and
  local convergence loops versus Atelier's durable Beads/message coordination,
  multi-worker execution, and PR/lifecycle orchestration
- this is not a failure of Atelier; it is a difference in orchestration model

Write `## Recommended Runtime Profile Cut` to define the feasible subset for a
future feature:

- repo-owned planner hardening guidance
- repo-owned worker hardening guidance
- additive verification/checklist behavior
- no new transport type
- no dependency on local trycycle installs

Write `## Required Architectural Changes` to describe what would be needed to
go further while preserving Atelier's functional intent. Include, at minimum:

- a durable feedback-loop record instead of ephemeral subagent chat
- a coordinator/supervisor model that can drive retries or review loops across
  planner and worker boundaries
- typed Beads/message artifacts for intermediate review and retry outcomes
- clearer planner-owned versus worker-owned split negotiation for oversized work
- a durable way to reconcile PR/review/publish state with iterative execution

Write `## Future Verification Floor` to record the agreed bar for any later
implementation slice:

- focused unit tests for config/selection/env behavior
- one planner launch-boundary scenario
- one worker launch-boundary scenario

Do not update current behavior docs or CLI docs in this slice. The new doc
should end with a short `## Recommended Follow-Up Slices` section naming the
next 2-3 implementation cuts, for example:

- repo-owned planner/worker runtime-profile scaffolding
- durable feedback-loop state model
- coordinator architecture for deeper iterative execution

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Re-read the document as an operator-facing decision package. It should answer:

- what is feasible now
- what is not feasible now
- why
- what must change later

Run:

```bash
just format
uv run pytest tests/atelier/test_trycycle_runtime_feasibility.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/trycycle-runtime-feasibility.md \
  tests/atelier/test_trycycle_runtime_feasibility.py
git commit -m "docs(runtime): publish trycycle feasibility verdict" \
  -m "- conclude that full trycycle-style runtime substitution is not currently feasible" \
  -m "- define the smaller repo-owned runtime-profile cut that is compatible with Atelier" \
  -m "- describe the architectural changes needed for deeper adaptation"
```

### Task 4: Verify, file follow-ups, and land the analysis package

**Files:**
- Modify if needed: `docs/trycycle-runtime-feasibility.md`
- Modify if needed: `tests/atelier/test_trycycle_runtime_feasibility.py`

- [ ] **Step 1: Identify any missing follow-up work**

Review the final `## Recommended Follow-Up Slices` section in
`docs/trycycle-runtime-feasibility.md`. If the document names concrete next
slices, create matching `bd` issues before ending the session.

Use exact titles from the document. Example commands:

```bash
bd create "Add repo-owned runtime profile scaffolding" \
  --description="Implement the feasible planner/worker hardening profile cut described in docs/trycycle-runtime-feasibility.md." \
  -t feature -p 1 --json

bd create "Design durable feedback-loop state for iterative worker runs" \
  --description="Define Beads/message artifacts for retry/review loop state without relying on ephemeral subagent chat." \
  -t feature -p 1 --json
```

- [ ] **Step 2: Run the required repo gates**

Run:

```bash
just test
just format
just test
just lint
```

Expected: all PASS.

- [ ] **Step 3: Fix any gate failures and rerun**

If any gate fails, repair the document or test and rerun the exact failing
command until it passes. Do not weaken the doc-contract test to force a green
result.

- [ ] **Step 4: Commit any last verification fixes**

If the quality gates required additional edits, commit them with a docs/test
message that reflects the actual delta.

- [ ] **Step 5: Push and verify**

Run:

```bash
git status --short
git pull --rebase
git push
git status
```

Expected:

- working tree is clean before push
- branch pushes cleanly
- final `git status` shows the branch is up to date with `origin`

- [ ] **Step 6: Hand off**

In the handoff note, summarize:

- the feasibility verdict
- the adoptable runtime-profile subset
- the architectural changes required for anything deeper
- any `bd` follow-up issues that were created

## Why this plan is the right cutover

- It lands the user's requested end state directly: a determination of whether
  trycycle-like planner/worker hardening fits Atelier, plus the mismatch
  analysis and future architecture guidance.
- It does not prematurely ship a `trycycle` feature that may be the wrong
  abstraction.
- It keeps the repo-owned source of truth decision intact.
- It respects Atelier's actual functional intent: durable orchestration,
  multiple workers, operator accountability, PR-driven late phases, and
  review-sized changesets.
- It still leaves a concrete path forward by naming the smaller `runtime
  profile` cut that is compatible with Atelier today and the deeper
  architectural work required for anything more ambitious.

# Atelier Reset Gate Proposal

## Decision requested

Approve or reject the destructive reset from the legacy Atelier CLI to the
skill-based Atelier described in [Atelier as a Skill].

Approval of the design pull request is not approval of this reset. Crossing the
gate still requires a second explicit operator confirmation after this document
is merged and reviewed. Until then:

- do not create or push the archival tag;
- do not create, close, relabel, or otherwise mutate Atelier issues; and
- do not remove or replace the legacy implementation.

## Proposed archival commit

Create the annotated tag `atelier-cli-v2-final` at:

```text
c08755f3a80c39b747df4cbf9be94e559d5081e2
```

This commit contains the final legacy implementation, the next-version design,
the implementation plan, and the reviewed composition experiment. The reset
proposal follows in a separate commit so it can name this target exactly. No
legacy implementation file changes between the proposed target and this
proposal.

The tag annotation should state that this is the final recoverable snapshot of
the standalone CLI and that the skill-based product supersedes it. The tag must
never be moved or reused.

## Validated prerequisite

Atelier depends on Agent Scripts as an independently installed platform. It does
not vendor or copy Agent Scripts workflows.

The validated dependency is:

- Agent Scripts commit: `861dd04c526d7e2ab7f33d112a00a370db17aae9`;
- installed plugin: `agent-scripts@agent-scripts` version `0.1.0`;
  - delegated capability: `agent-scripts.implement-ticket/delegated-execution/v2`;
- installed `implement-ticket` skill SHA-256:
  `307b660864b15a167e755d0f47840acb56d20e1e8ec940d110d84548aec85243`; and
- capability manifest SHA-256:
  `551d2e883d226d2a1e7e39eae66eb2bd3d9d88ec18c56cfba190253677e34156`.

Agent Scripts owns native-ticket implementation, candidate publication, review,
pull-request lifecycle, changeset carving, and post-publication behavior.
Atelier owns approved intent, project policy, authority fencing, durable
planner-worker coordination, terminal-result validation, audit, and operator
acceptance.

## Composition evidence

The exact reviewed experiment used:

- Atelier composition plugin version `0.1.0+codex.20260726184539`;
- Atelier skill SHA-256
  `2e9a2d47405093c6cd24df7d08bb79f3cdb37bfb92de50d94231d2f971ad8539`;
- `codex-cli 0.145.0`;
- Codex executable SHA-256
  `1da3f4e0e96028b8a771814293c3033dafd1971f943f6c7e79b0897fe705f590`; and
- the separately installed Agent Scripts dependency identified above.

The final verifier passed nine of nine scenarios:

1. an allowed worker produced a reviewed, pushed candidate and fixture
   `ready_pr`;
1. a denied PR mutation preserved a reviewed, pushed, transferable candidate and
   returned `blocked`;
1. a malformed capability was rejected;
1. excess terminal authority was rejected;
1. a candidate-acknowledgement mismatch was rejected;
1. a foreign invocation could not consume checkpoint state;
1. an excluded action was denied before mutation;
1. a stale sequence could not consume checkpoint state; and
1. a foreign repository could not consume checkpoint state.

The accepted evidence root was archived outside `/tmp` at:

```text
/Users/scott/.codex/evidence/atelier/2026-07-26-composition-reviewed-vVFqyD/
```

The exact archive is `atelier-composition-reviewed.vVFqyD.tar.gz` in that
directory.

The archive SHA-256 is:

```text
6689d90718351094feaef8c15e23bfed46477e9714626f6a8ef0c2f3b0b643ae
```

Its 544-entry `SHA256SUMS` manifest has SHA-256:

```text
edcf9764899464f91e56c59d45e6c87bf775d2a2a758491e261143845fa69578
```

The repository retains the experiment source under
`experiments/codex-composition-eval/`. The archive retains the exact raw
invocations, checkpoint exchanges, Git repositories, worker and reviewer
transcripts, terminal results, verifier output, installed package bytes, and
pinned Codex executable used by the final review.

## Adversarial-review disposition

The final independent review returned `PASS WITH FOLLOWUPS`: no material
composition, authority, durability, provenance, or evaluation-validity blocker
remains.

The review independently recomputed package manifests, confirmed source and
installed-package equivalence, resolved both candidate refs to their reported
heads, traced worker-to-reviewer causality, verified read-only fresh reviewer
processes, inspected denied-state immutability, and confirmed the nine-scenario
denominator.

The following limits are binding:

- `ready_pr` in the experiment is a local provider fixture, not a live GitHub
  pull request;
- the experiment proves cooperative host-native Codex composition, not
  containment of a malicious worker;
- it does not validate a production Atelier implementation;
- it does not validate live GitHub API behavior; and
- it does not validate Claude Code compatibility.

Those are later vertical-slice and product-validation obligations. They are not
reasons to preserve the legacy orchestrator.

## Proposed implementation issue graph

Create the following graph only after reset confirmation. The identifiers below
are proposal-local names; the created GitHub issues will receive native issue
numbers.

- `ATELIER-V0` — Epic: prove accountable skill-based development.
- `RESET` — Push the archive tag, disposition legacy issues, and replace the CLI
  with a minimal plugin skeleton. Depends on reset confirmation.
- `HOST` — Discover `/atelier` in Codex, establish the read-only native-state
  connector boundary, and fail closed unless the exact Compris capability
  is available. Depends on `RESET`.
- `MAILBOX` — Validate mailbox root, project, initiative, work, message,
  receipt, acceptance, and policy documents. Depends on `RESET`.
- `GIT-WRITES` — Perform fast-forward-only mailbox writes with semantic retry,
  remote read-back, and ambiguous-result recovery. Depends on `MAILBOX`.
- `PLAN` — Draft, revise, approve, and promote one assignment tied to one native
  GitHub ticket. Depends on `HOST` and `GIT-WRITES`.
- `CLAIM` — Derive project-serial eligibility and maintain fenced claims and
  checkpoint ledgers. Depends on `PLAN` and `GIT-WRITES`.
- `DELEGATE` — Invoke the installed Compris capability and record a
  validated blocked or delivered receipt. Depends on `HOST` and `CLAIM`.
- `AUDIT` — Re-read native ticket, PR, review, and check state through the host
  connector and record explicit operator acceptance only when every evidence
  predicate is current. Depends on `HOST`, `MAILBOX`, and `DELEGATE`.
- `DOGFOOD` — Deliver one human-shaped Atelier changeset through separate
  planner and worker tasks. Depends on `PLAN`, `CLAIM`, `DELEGATE`, and `AUDIT`.
- `CROSS-PROJECT` — Run one Tuber and Peeler initiative with independent
  repository delivery and acceptance. Depends on `DOGFOOD`.
- `CONSTRAINED` — Validate useful coordination where Atelier cannot mutate the
  native tracker. Depends on `DOGFOOD`.

`RESET` through `DOGFOOD` are children of `ATELIER-V0`. `CROSS-PROJECT` and
`CONSTRAINED` are post-v0 product-validation issues, not requirements for the
first production vertical slice.

Do not create provider expansion, Claude Code, parallel project execution,
automatic merge, deployment, dashboards, SQLite, server, projection, migration,
or backward-compatibility issues unless later evidence justifies them.

## Live legacy issue disposition

This inventory was refreshed from GitHub on 2026-07-26. It contains all 43 open
issues. Each issue receives one primary disposition:

- `superseded`: the outcome is now owned by Agent Scripts or a different
  boundary;
- `cancelled`: the issue exists only because of abandoned machinery or
  compatibility;
- `retained doctrine`: the lesson survives, but the implementation issue does
  not; or
- `newly represented`: a proposed issue above directly carries the surviving
  work.

After reset confirmation, create the replacement graph first. Then close every
legacy issue with its mapped disposition, rationale, a link to this proposal,
and links to created replacement issues where named. Do not mark these issues
`completed`.

- **#770 — GitHub issue/export provider migration:** `superseded` by the Agent
  Scripts native-ticket boundary and `DELEGATE`.
- **#769 — Duplicate GitHub issue/export provider migration:** `superseded` by
  the #770 disposition.
- **#768 — PR mutation and review-thread provider migration:** `superseded` by
  the Agent Scripts PR lifecycle.
- **#767 — PR lifecycle read-path provider migration:** `newly represented` by
  the read-only native-state boundary in `HOST` and the live evidence predicates
  in `AUDIT`.
- **#766 — Atelier-owned GitHub boundary models:** `superseded` by the Agent
  Scripts capability contract, `HOST`, and `DELEGATE`.
- **#754 — Dolt overflow compaction transactions:** `cancelled`; there is no
  database or Dolt.
- **#752 — Non-durable Dolt SQL writes:** `cancelled`; there is no database or
  Dolt.
- **#749 — Dolt overflow compaction persistence:** `cancelled`; there is no
  database or Dolt.
- **#740 — Epic-close stale PR lifecycle:** `superseded` by the Agent Scripts
  epic and PR lifecycle.
- **#738 — Beads overflow recovery:** `cancelled`; there is no Beads store.
- **#736 — Planner startup queue filtering:** `newly represented` by `PLAN` and
  `CLAIM` eligibility derivation.
- **#719 — Trycycle-ready Beads contracts:** `cancelled`; there is no Beads
  runtime, and Atelier is not Trycycle.
- **#718 — Trycycle-powered bounded worker runtime:** `cancelled`; Agent Scripts
  delegation replaces the worker runtime.
- **#712 — Concurrent description-update conflicts:** `newly represented` by
  `GIT-WRITES` and `CLAIM` compare-and-swap semantics.
- **#711 — Beads event-log overflow:** `cancelled`; there is no Beads event log.
- **#706 — Plan promotion notes preview:** `newly represented` by the `PLAN`
  approved-work document.
- **#694 — Projected skill bootstrap:** `newly represented` by `HOST` exact
  plugin and capability discovery.
- **#690 — Fast-local-first worker worktrees:** `superseded` by Agent Scripts
  candidate isolation.
- **#689 — Duplicate fast-local-first worker worktrees:** `cancelled` by the
  #690 disposition.
- **#679 — Planner policy and boundary ownership:** `retained doctrine` in the
  `PLAN`, `CLAIM`, and `AUDIT` authority boundaries.
- **#677 — Mailbox unread mode:** `newly represented` by `MAILBOX` receipts and
  `AUDIT` derived views.
- **#675 — Deterministic changeset resplit:** `retained doctrine` in Agent
  Scripts `carve-changesets`; Atelier does not implement it.
- **#666 — Store-shaped dependency parsing:** `cancelled`; there is no Beads or
  store payload.
- **#655 — Planner skill import drift:** `newly represented` by `HOST` exact
  discovery and fail-closed startup.
- **#644 — Dual-backend compatibility and migration:** `cancelled`; there is no
  compatibility or migration.
- **#643 — Store contract and invariants:** `retained doctrine` in `MAILBOX` and
  `GIT-WRITES` contracts.
- **#631 — Inactive-worker message rerouting:** `retained doctrine` in `MAILBOX`
  work-thread identity and explicit routing.
- **#628 — Null worktree mapping IDs:** `cancelled`; there is no Atelier
  worktree registry.
- **#617 — `atelier.testing.beads` adoption:** `cancelled`; there is no Beads
  testing backend.
- **#615 — Beads client and test boundary:** `cancelled`; there is no Beads
  client.
- **#597 — Python 3.14 legacy suite support:** `cancelled`; the legacy Python
  CLI is removed.
- **#592 — Blocking messages before execution:** `newly represented` by
  `MAILBOX` and `CLAIM` eligibility.
- **#591 — Duplicate blocking-message issue:** `cancelled` by the #592
  disposition.
- **#590 — Work-threaded durable messages:** `newly represented` by `MAILBOX`.
- **#585 — Drain `beads.py` facade:** `cancelled`; the whole legacy store is
  removed.
- **#584 — Review/publish issue-store migration:** `cancelled`; Agent Scripts
  owns review and publication.
- **#573 — Atelier-owned GitHub provider abstraction:** `superseded` by the
  Agent Scripts provider boundary.
- **#472 — CLI enum help:** `cancelled`; the standalone Typer CLI is removed.
- **#466 — In-memory Beads backend:** `cancelled`; there is no Beads backend.
- **#459 — Prefix-migration metadata repair:** `cancelled`; there is no
  migration or workspace registry.
- **#382 — Hotspot architecture guardrails:** `retained doctrine` in `RESET` and
  the independently reviewable graph nodes.
- **#377 — Worker startup/finalization service extraction:** `cancelled`; the
  worker runtime is removed.
- **#324 — Pre-PR formal changeset review:** `retained doctrine` in Agent
  Scripts independent review, `DELEGATE`, and `AUDIT`.

Disposition totals are 7 superseded, 21 cancelled, 6 retained-doctrine, and 9
newly represented issues.

## Exact deletion and replacement boundary

The reset pull request should remove these tracked paths:

- `src/atelier/**`;
- `tests/**`;
- `evals/**`;
- every `docs/**` file except:
  - `docs/atelier-name.md`;
  - `docs/atelier-skill-design.md`;
  - `docs/git-mailbox-contract.md`;
  - `docs/implementation-plan.md`;
  - `docs/mailbox-protocol-validation.md`;
  - `docs/north-star.md`;
  - `docs/project-policy-contract.md`; and
  - `docs/reset-gate-proposal.md`;
- legacy runtime and maintenance scripts:
  - `scripts/atelier-work.py`;
  - `scripts/hotspot_complexity_report.py`;
  - `scripts/repair_tool_install.py`;
  - `scripts/lint-gate.sh`; and
  - `scripts/supported-python.sh`;
- `CLAUDE.md`;
- `.release-please-manifest.json`; and
- `release-please-config.json`.

The same reset pull request should replace, rather than preserve for
compatibility:

- `AGENTS.md` with instructions for the skill/plugin product;
- `README.md` with the new product claim and installation boundary;
- `CHANGELOG.md` with a reset notice rather than a migrated CLI history;
- `pyproject.toml` with only tooling still required by the plugin and
  experiments, if Python remains necessary at all;
- `justfile` with gates for the new repository shape;
- `.github/**` with plugin-oriented CI and release behavior;
- `.githooks/**` with gates that invoke only the new toolchain; and
- `.gitignore` with only current generated-state exclusions.

Retain unchanged unless a concrete new-tooling need says otherwise:

- `.mdformat.toml`;
- `commitlint.config.cjs`;
- `LICENSE`;
- `experiments/mailbox_protocol_v0.py`; and
- `experiments/codex-composition-eval/**`.

The reset must not leave a dormant legacy package, compatibility command,
migration reader, copied Compris workflow, Beads adapter, Dolt helper,
SQLite projection, server stub, or alternate runtime path.

## Destructive preflight

Before the first reset mutation, all of these checks must pass in one refreshed
observation:

- the live open-issue number set equals exactly:

  ```text
  324 377 382 459 466 472 573 584 585 590 591 592 597 615 617 628 631
  643 644 655 666 675 677 679 689 690 694 706 711 712 718 719 736 738
  740 749 752 754 766 767 768 769 770
  ```

- every changed issue title, body, state, dependency, or scope-affecting comment
  has been reviewed against its mapped disposition; equal count alone is not
  sufficient;

- remote tag `atelier-cli-v2-final` is absent, and the proposed target is
  reachable from the reviewed default-branch history;

- the evidence archive and `SHA256SUMS` manifest reproduce the hashes recorded
  above, and the nine-scenario verifier still passes from the preserved bytes;

- the current tracked tree has been classified by the deletion, replacement, and
  retention rules above, with exact path-set equality and no unclassified file
  beneath a destructive path; and

- `main`, the design pull request, required CI, and exact-head review have no
  unresolved drift that changes this decision.

Any mismatch stops before mutation and requires a revised proposal or explicit
operator disposition.

## Rollback and recovery

The reset is destructive to the default branch but recoverable:

1. Verify that `atelier-cli-v2-final` resolves remotely to the proposed commit
   before merging any deletion.
1. Preserve the evidence archive and its checksum manifests independently of the
   repository checkout.
1. Record every created replacement issue and every closed legacy issue in the
   `RESET` issue as each provider mutation succeeds. If `RESET` creation itself
   fails, use `ATELIER-V0` as the recovery record.
1. Merge the reset as one reviewable pull request whose deletion and minimal
   skeleton are easy to revert together.
1. If replacement-graph creation stops partway, resume idempotently from the
   recorded native issue IDs. If the reset is abandoned, close every newly
   created replacement issue as `cancelled`; leave all legacy issues and the tag
   untouched.
1. If legacy closure stops partway, stop further mutation and record the exact
   closed set. If the reset is abandoned, reopen only that set with rollback
   comments, close the replacement graph as `cancelled`, and verify that the
   exact 43-number open set is restored. An already pushed archival tag remains
   immutable.
1. If abandonment occurs after graph creation or legacy closure fully completes,
   apply the same rollback to the complete recorded sets: reopen every legacy
   issue closed by the reset, close every replacement issue as `cancelled`, and
   leave any pushed archival tag immutable.
1. If the reset pull request is abandoned before merge, close it without
   changing `main`. If a merged reset is wrong, revert that pull request on
   `main`; do not build a compatibility layer.
1. If the old CLI must be recovered independently, create a recovery branch from
   `atelier-cli-v2-final` and install it from that branch. Never move the tag.
1. If dogfooding disproves the product thesis, keep the archival tag and
   evidence, then either revert the reset or start another explicit design
   decision. Do not respond by adding a database, daemon, or dual architecture.

There is intentionally no forward migration from Beads, Dolt, legacy project
configuration, sessions, or worktrees. Recovery means running the archived
product, not making old data silently valid in the new one.

## Reset execution after confirmation

If the operator explicitly confirms this gate:

1. run the complete destructive preflight above;
1. create `ATELIER-V0` and then `RESET`, record both native issue numbers, and
   use `RESET` as the durable execution record;
1. create the rest of the proposed issue graph one issue at a time, recording
   each native identity and verifying its relationships before continuing;
1. create and push the annotated `atelier-cli-v2-final` tag at the exact commit,
   resolving an ambiguous push by remote read-back and never overwriting a
   different tag;
1. close all 43 legacy issues one at a time with the mapped non-completion
   disposition, recording each success in `RESET`;
1. implement `RESET` as a human-shaped pull request;
1. obtain exact-head review and required CI;
1. merge only with separately confirmed authority; and
1. begin `HOST` and `MAILBOX` from the new graph.

If any prerequisite, checksum, exact issue set or meaning, tag state, or tracked
path classification has drifted, stop and present the difference before
mutation.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier as a skill]: atelier-skill-design.md

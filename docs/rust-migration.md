# Rust Migration Plan

This document outlines a Rust implementation plan for the Atelier CLI, aiming
for behavioral parity with the existing Python implementation while improving
cold-start latency and distribution ergonomics.

## Goals

- Match CLI behavior and flags as closely as possible.
- Preserve data directory layout and config file semantics.
- Favor compatibility (especially with Git operations and auth).
- Keep changes incremental and reviewable.

## Recommended Crates

Core CLI and UX:
- `clap` (derive): command-line parsing and help output.
- `clap_complete`: generate completion scripts.
- `dialoguer` or `inquire`: interactive prompts (with TTY detection).
- `is-terminal`: determine whether to use interactive prompts.

Config, serialization, and validation:
- `serde`, `serde_json`: config files and templates.
- `validator` or custom validation functions: Pydantic-like rules.
- `thiserror`: error definitions.

Filesystem and paths:
- `directories` (or `directories-next`): `platformdirs` equivalent.
- `fs-err`: richer filesystem errors.
- `sha2`: SHA-256 for project/workspace keys and managed file hashes.

Process and Git integration:
- `std::process::Command`: subprocess invocation for Git and agent CLIs.
- `which`: agent CLI detection.

PTY and Codex session capture:
- `portable-pty` (if cross-platform support is required).
- `regex`: session parsing in PTY output.

Testing:
- `assert_cmd`, `predicates`: CLI-level tests.
- `tempfile`: isolated filesystem fixtures.
- `insta` (optional): snapshot tests for CLI output.

## Key Choices (and Rationale)

### Git Operations: Shell Out to `git`
Decision: use `git` subprocesses (not `git2/libgit2`).

Rationale:
- Best compatibility with user config, credential helpers, SSH setup, and
  custom transports.
- Minimizes surprising behavior for users with non-standard Git setups.

Implications:
- Slightly slower than in-process `git2`, but Git I/O dominates runtime
  regardless.
- Requires Git on PATH (same as current behavior).

### CLI Flags and Completions: Match Typer
Decision: implement the same flags and options, including:
- `--show-completion`
- `--install-completion`

Implementation note:
- `clap_complete` can generate scripts; we will replicate Typer's command-line
  UX by accepting the same global flags and (optionally) a shell name. When
  omitted, use environment-based detection as Typer does.

### PTY Capture
Decision: plan for `portable-pty` for cross-platform parity, with a clear
fallback strategy for Unix-only environments.

Risk:
- PTY handling has more moving parts than direct Unix `pty` + `termios`.
- Requires careful I/O pumping, resizing, and raw mode handling.

## Compatibility With Current Data Directories

The Rust implementation must preserve all on-disk conventions:

- Data directory root: `platformdirs`-equivalent location used today.
- Project/workspace keys and layout:
  - `projects/<project-key>/`
  - `workspaces/<workspace-key>/`
  - `config.sys.json`, `config.user.json`
  - policy files (`AGENTS.md`, `PROJECT.md`, `SUCCESS.md`, `PERSIST.md`,
    `BACKGROUND.md`)
- Hashing rules:
  - short SHA-256 suffixes for project/workspace directory names
  - stable workspace ID: `atelier:<enlistment-path>:<branch>`
- Managed template hashing behavior must remain identical to avoid accidental
  overwrite prompts or silent upgrades.

Potential pitfalls:
- Path normalization differences between Python and Rust (especially around
  Unicode normalization, `Path` canonicalization, and `.resolve()` behavior).
- Ensuring that legacy origin-based project keys are still recognized.

## Estimated Cold Start Improvements

Expected benefit: faster cold start and lower steady-state memory.

Estimates (order-of-magnitude, platform-dependent):
- Python CLI: typically 200-600 ms cold start due to interpreter + imports.
- Rust CLI: typically 20-80 ms cold start for small binaries.

Net improvement: ~3-10x faster startup, especially noticeable for commands that
only read config and exit (e.g., `atelier --version`, `atelier list`).

Note: Git subprocess calls and filesystem I/O will dominate runtime for heavy
commands like `open` or `clean`.

## Challenges and Trade-offs

- **PTY session capture**: cross-platform PTY behavior varies; robust handling
  requires careful design and testing on Linux/macOS/Windows.
- **Config validation**: Pydantic's "extra=allow" and validators must be
  recreated in Rust using `serde` and explicit validation functions.
- **Interactive prompts**: must match behavior when stdin/stdout are not TTYs.
- **Error messages**: user-facing errors should match existing phrasing as much
  as possible to reduce user surprise and test churn.

## Compatibility Test Plan (Existing Python Data)

We should explicitly test compatibility against projects/workspaces created by
the Python CLI since the Rust CLI will be a drop-in replacement.

Recommended approach:
- Fixture-based tests that load real on-disk data directory structures created
  by the Python CLI (both fresh and legacy).
- Cross-version tests that run the Rust CLI against a data dir created by the
  Python CLI and verify:
  - detection and enumeration of projects/workspaces
  - template upgrade policy behavior
  - workspace reuse without recreation
  - finalization tags are honored
  - managed file hashes are stable
- "Round trip" tests:
  - create a project/workspace with Python CLI
  - run Rust CLI to open/work/clean
  - verify files and metadata are unchanged except for expected fields
- Branch layout tests:
  - prefixed vs raw workspace names
  - legacy origin-based keys still resolved
- Snapshot CLI output tests for key commands to confirm output parity.

## Repository Transition (Python → Rust)

The Rust CLI will replace the Python CLI, so the repository should evolve into a
Rust-first project:

- Add Cargo workspace (`Cargo.toml`, `src/`) and update build/test tooling.
- Replace the Python `pyproject.toml` as the primary build definition.
- Update README, docs, and release scripts to point to the Rust binary.
- Keep Python sources only if needed for a temporary transition period; plan a
  staged removal once Rust reaches parity.
- Update versioning and distribution (e.g., release artifacts, installers,
  package manager formulas) to point at Rust build outputs.

## Full Implementation Plan

Phase 0: Scaffolding and parity strategy
- Define command/flag matrix matching current CLI behavior.
- Agree on data directory compatibility and hashing rules.

Phase 1: Core libraries and types
- Implement `paths`:
  - data directory resolution
  - project/workspace directory naming
  - short SHA-256 hashing helpers
- Implement `config`:
  - schema structs for project/workspace configs
  - `extra` fields via `serde(flatten)`
  - validation and normalization logic (prefix, branch history, agent names)

Phase 2: Git and process layer
- Implement `exec` helpers:
  - run command
  - run git command
  - try-run for optional binaries
- Implement `git` helpers:
  - normalize origin URL (SCP, URL, file, local path)
  - branch detection and status (clean/pushed)
  - default branch resolution

Phase 3: Templates and policy files
- Implement template copy/link behavior with symlink fallback.
- Implement managed file hashing and upgrade policy logic.
- Ensure template assets match current repo structure.

Phase 4: Workspace mechanics
- Implement workspace identifier and directory resolution.
- Workspace creation and lookup logic:
  - candidate branches (prefix + raw)
  - legacy directory fallback
  - workspace config checks

Phase 5: CLI commands (parity-focused)
- `init`: register project, scaffold templates/config.
- `new`: create repo + init + open.
- `open`: resolve workspace, clone repo, create branch, policies, open editor,
  start agent.
- `work`, `shell`, `exec`: open workspace context and run user commands.
- `list`: display workspaces and statuses.
- `clean`: remove finalized workspaces and (optionally) remote branches.
- `edit`, `template`, `upgrade`, `config`: template and config management.
- Global flags:
  - `--version`
  - `--show-completion`
  - `--install-completion`

Phase 6: Agent integration
- Implement agent detection and option assembly.
- Codex PTY capture and session parsing.
- Resume metadata handling (session ID, resume command).

Phase 7: Testing and validation
- Unit tests for path normalization, hashing, config validation.
- CLI tests for key flows: init/open/list/clean.
- End-to-end tests on a temp repo with local git.

Phase 8: Performance and polish
- Measure cold-start with a simple benchmark harness.
- Trim dependency weight where possible.
- Ensure error messages remain user-friendly and familiar.

Phase 9: Repository transition
- Introduce Cargo build and CI workflows for Rust.
- Update documentation and release tooling.
- Remove or archive Python implementation once parity is confirmed.

## Implementation Notes

- Preserve exact default values in config (e.g., branch history policy).
- Avoid "help text drift": use the same phrasing and command examples where
  possible.
- Keep output text compatible with existing docs and tests.

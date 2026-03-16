# Projected Skill Runtime Contract

Projected skill scripts that import `atelier` run under a shared bootstrap
contract. The contract is implemented in `src/atelier/runtime_env.py` and
consumed by `src/atelier/skills/shared/scripts/projected_bootstrap.py`.

## Supported modes

- `repo-source`: bootstrap has proven a checkout with `src/atelier`, so the
  projected script prefers repo source imports and may switch to a deterministic
  repo interpreter before importing heavier `atelier` modules.
- `active-interpreter`: bootstrap has not proven a repo checkout, so the
  projected script stays in the current interpreter and must prove dependency
  health there before importing heavier `atelier` modules.

## Provenance selection rules

1. Resolve repo provenance explicitly from `--repo-dir`, the local `./worktree`
   link, projected repo env hints, then `cwd` and script ancestry.
1. Use `repo-source` mode only after bootstrap proves a checkout with
   `src/atelier` is available to the projected script.
1. Runtime health checks must prove transitive dependencies, not just partial
   `atelier` importability, before projected scripts import heavier modules.

## Inherited `PYTHONPATH` rules

1. Do not trust inherited `PYTHONPATH` as ambient input. Before runtime health
   checks, clear it or reduce it to import roots already proven to belong to the
   selected runtime.
1. In `active-interpreter` mode, inherited `PYTHONPATH` entries may remain only
   when they are the active interpreter's required dependency roots and
   bootstrap has not yet replaced them with equivalent explicit paths.
1. In `repo-source` mode, discard inherited `PYTHONPATH` entries from other
   distributions and preserve or reintroduce only explicit selected-runtime
   paths, such as `repo_root/src` after selection succeeds.
1. Do not treat ambient `PYTHONPATH` as healthy merely because `atelier`
   imports; transitive dependency health and provenance still must be proven.

## `repo_root = None`

When `repo_root` is `None`, projected bootstrap does not guess a repo runtime.
It stays in `active-interpreter` mode, skips repo-runtime re-exec, and reports
that operators must pass `--repo-dir <repo-root>` or run from an agent home with
a local `./worktree` link when repo-source behavior is required.

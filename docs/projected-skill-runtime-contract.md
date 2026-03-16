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

1. Discard inherited `PYTHONPATH` entries before runtime health checks so
   projected scripts do not mix packages from different distributions.
1. Preserve or reintroduce only explicit paths required by the selected runtime,
   such as `repo_root/src` after `repo-source` selection succeeds.
1. Do not keep ambient `PYTHONPATH` entries just because `atelier` already
   imports; partial imports without transitive dependencies are not healthy.

## `repo_root = None`

When `repo_root` is `None`, projected bootstrap does not guess a repo runtime.
It stays in `active-interpreter` mode, skips repo-runtime re-exec, and reports
that operators must pass `--repo-dir <repo-root>` or run from an agent home with
a local `./worktree` link when repo-source behavior is required.

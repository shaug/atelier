# Versioning and releases

Atelier uses Conventional Commits and Release Please to drive SemVer releases.

## Commit requirements

- Commit messages must follow Conventional Commits (enforced in CI).
- No squash-merge required. Release notes can be edited in the Release PR before merging.

## Release flow

1) Release Please runs on pushes to `main` and opens/updates a Release PR.
2) The Release PR updates `CHANGELOG.md` and `.release-please-manifest.json`.
3) Merging the Release PR creates the `vX.Y.Z` tag and a GitHub Release.
4) The release-artifacts workflow builds sdist + wheel and uploads them to the Release.

Note: if you want the release-artifacts workflow to run on the release event, set a
`RELEASE_PLEASE_TOKEN` secret (a PAT with `contents: write`) so the release creation
can trigger other workflows.

## Dev versions

We use `hatch-vcs` for commit-unique dev versions:

- Tagged builds (e.g., `v0.2.0`) resolve to `0.2.0`.
- Non-tagged commits resolve to a dev build identifier (for example
  `0.2.0.devN+g<sha>`).

The version file (`src/atelier/_version.py`) is generated at build or install time.
Editable installs will not update the version until you rebuild or reinstall.

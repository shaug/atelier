# Skill: github

## Purpose

Provide deterministic operations for GitHub pull requests used by Atelier
workflows.

## Supported Operations

- create: open a pull request for a workspace branch.
- update: change PR base, title, or description when required.
- inspect: read PR status and metadata for verification.

## Owned State

- Pull request metadata (title, body, base, labels) for the workspace branch.

## Invariants

- Operations must be explicit and parameterized (no inferred intent).
- PR mutations must reflect the workspace branch state.
- Changes must be idempotent when re-run with the same parameters.

## Prohibited Actions

- Do not invoke `atelier` to mutate state.
- Do not modify local workspace files unless explicitly required for the PR.
- Do not change repository settings outside the PR scope.

## Allowed Verification Calls

- `atelier describe --format=json`
- `atelier list --format=json`

## Notes

Use the GitHub CLI or provider APIs as appropriate, but always verify the
resulting state before returning success. Delegate issue workflows to the
`github-issues` skill.

# Skill: github

## Purpose

Route GitHub workflows to the dedicated skills that implement them.

## Supported Operations

- delegate: map PR workflows to `github-prs` and issue workflows to
  `github-issues`.

## Invariants

- Keep operations explicit and parameterized; do not infer repo, base, or head.
- Preserve clear separation between PR and issue responsibilities.

## Prohibited Actions

- Do not create, update, retarget, or inspect pull requests here.
- Do not create, update, read, or close issues here.
- Do not invoke `atelier` to mutate state.
- Do not change repository settings outside delegated scope.

## Notes

Use `github-prs` for pull request workflows and `github-issues` for issue
workflows.

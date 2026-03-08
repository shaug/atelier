# North-Star Review Gate

Use this runbook when a worker changeset is ready to commit, push, or publish.
The worker must prove that the assigned bead's acceptance criteria are fully
implemented before any outbound change is allowed.

## Required Artifact

Before the first push, append a note to the changeset bead with this shape:

```text
north_star_review.<timestamp>:
1) unmet_acceptance_criteria: none
2) required_code_changes_per_criterion:
- AC1: <required code change>
- AC2: <required code change>
3) implementation_summary:
- <what changed to satisfy the criteria>
4) completion_checklist:
- AC1 satisfied by commit <sha>; files: path/to/file.py.
- AC2 satisfied by verification: <result>; files: path/to/test_file.py.
```

Rules:

- `unmet_acceptance_criteria` must be `none` before publish.
- Every acceptance criterion in the bead must appear in
  `required_code_changes_per_criterion`.
- Every acceptance criterion in the bead must appear in `completion_checklist`.
- Each checklist line must include evidence such as a commit SHA, a file path,
  or an explicit verification record.
- If multiple north-star notes exist, the latest `authoritative: true` block
  wins. Otherwise the latest block wins.

## Worker Flow

1. Read the epic and assigned changeset bead.
1. Copy every acceptance criterion and non-goal into a working checklist.
1. Implement the code, tests, docs, or config required by the changeset.
1. Before any commit, push, or publish attempt, append the
   `north_star_review.<timestamp>:` note.
1. Confirm the note says `unmet_acceptance_criteria: none`.
1. Confirm each criterion has both:
   - a required-code-change entry
   - a completion-checklist entry with commit/file evidence
1. Rerun finalize or publish only after the bead note is complete.

If the gate blocks publish, the worker should expect a blocked reason of
`north-star review checklist incomplete` plus an audit note beginning with
`publish_blocked: north-star review gate failed`.

## Planner Audit

Use this checklist before accepting worker completion:

1. Open the changeset bead with `bd show <changeset-id>`.
1. Find the active `north_star_review.<timestamp>:` block.
1. Verify all four sections exist:
   - `unmet_acceptance_criteria`
   - `required_code_changes_per_criterion`
   - `implementation_summary`
   - `completion_checklist`
1. Verify `unmet_acceptance_criteria` is `none`.
1. Count the bead acceptance criteria and confirm the note maps each one.
1. Confirm every checklist entry cites concrete evidence:
   - commit SHA
   - file path
   - explicit verification result
1. If any mapping or evidence is missing, keep the changeset blocked and send
   the worker back to repair the note before another publish attempt.

## Migration Notes

This gate applies immediately to in-flight worker sessions.

- If a session started before the prompt/template rollout but has not pushed
  yet, append the north-star note before the first push.
- If a session is already blocked by the publish gate, repair the bead note and
  rerun finalize. Do not clear the block with comments alone.
- If a branch was pushed before the rollout and no terminal PR/integration proof
  exists yet, add the north-star note before the next publish or PR update.
- Planner review should treat missing or partial north-star notes as a failed
  handoff, not a best-effort warning.

---
name: changeset-review
description: >-
  Update changeset review metadata fields (pr_url, pr_number, pr_state,
  review_owner) through the AtelierStore review contract.
---

# Changeset review update

## Inputs

- changeset_id: Bead id of the changeset.
- pr_url: Optional PR URL.
- pr_number: Optional PR number.
- pr_state: Optional PR state (pushed, draft-pr, in-review, approved, merged).
- review_owner: Optional reviewer identity.
- beads_dir: Optional Beads store path.

## Steps

1. Show the changeset bead:
   - `bd show <changeset_id>`
1. Read [Publish Store Migration Contract] before mutating review metadata.
1. Persist the review metadata through AtelierStore-owned review update
   operations (`atelier.store.UpdateReviewRequest`) rather than editing
   Beads-shaped description fields directly.
1. Keep lifecycle status authoritative
   (`deferred|open|in_progress|blocked|closed`). `cs:*` lifecycle labels are not
   execution gates.
1. Verify the resulting changeset still exposes the expected `pr_url`,
   `pr_number`, `pr_state`, and `review_owner` fields when read back.

## Verification

- The changeset bead description includes the updated review metadata fields.

<!-- inline reference link definitions. please keep alphabetized -->

[publish store migration contract]: ../../../docs/publish-store-migration-contract.md

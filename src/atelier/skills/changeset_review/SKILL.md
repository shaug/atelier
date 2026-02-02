---
name: changeset_review
description: >-
  Update changeset review metadata fields (pr_url, pr_number, pr_state,
  review_owner) in a changeset bead description.
---

# Changeset review update

## Inputs

- changeset_id: Bead id of the changeset.
- pr_url: Optional PR URL.
- pr_number: Optional PR number.
- pr_state: Optional PR state (open, review, changes_requested, approved,
  merged).
- review_owner: Optional reviewer identity.
- beads_dir: Optional Beads store path.

## Steps

1. Show the changeset bead:
   - `bd show <changeset_id>`
1. Update the description fields (`pr_url`, `pr_number`, `pr_state`,
   `review_owner`).
1. Write the new description with `bd update <changeset_id> --body-file <path>`.

## Verification

- The changeset bead description includes the updated review metadata fields.

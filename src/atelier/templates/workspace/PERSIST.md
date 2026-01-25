<!--
PERSIST.md

This file describes how to finish and integrate the work in this workspace.
It is managed by Atelier and derived from workspace settings.
-->

# Persistence Guide

Read this file before finalizing work or integrating changes.

{integration_strategy}

## Publishing

{publish_instructions}

## Finalization

After publishing is complete, integrate changes onto the default branch per the
history policy, push the default branch to the remote, then identify the
integration commit and create the local finalization tag.

- Manual: wait for explicit instruction to finalize after the merge lands.
- Squash: tag the single squash commit created on the default branch.
- Merge: tag the merge commit on the default branch.
- Rebase: tag the rebased tip commit on the default branch.

```sh
git tag atelier/<branch-name>/finalized
```

Do not push this tag to the remote. `atelier clean` deletes workspaces only when
this tag exists.

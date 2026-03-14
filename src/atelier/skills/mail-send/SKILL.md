---
name: mail-send
description: >-
  Send a work-threaded message by creating a message issue with YAML
  frontmatter.
---

# Mail send

Work-threaded messages are the durable coordination path. `mail-send` supports
only work-threaded coordination and fails closed when `--thread` is omitted. Use
`to` only to describe the intended audience and, when helpful, to nudge the
current runtime.

## Inputs

- subject: Message subject line.
- body: Message body content.
- to: Recipient agent id used to derive audience metadata and optional assignee
  hints.
- from: Sender agent id.
- thread: Required work thread id (epic or changeset bead id).
- reply_to: Optional message id being replied to.
- beads_dir: Optional Beads store path.

## Steps

1. Use the dispatch script:
   - `python skills/mail-send/scripts/send_message.py --subject "<subject>" --body "<body>" --to "<to>" --from "<from>" --thread "<thread>" [--reply-to "<reply_to>"] [--beads-dir "<beads_dir>"]`
1. `mail-send` requires `--thread <epic-or-changeset>`:
   - the script adds `thread_target`, `audiences`, and default `kind` metadata
   - worker-targeted threaded messages also add `blocking_roles: [worker]`
1. Do not create planner-to-worker message beads directly with `bd create`.
1. Treat work-threaded delivery as the durable model:
   - when `thread` is present, the script emits work-thread metadata (`thread`,
     `thread_kind`, `audience`, `kind`, `delivery`)
   - the message stays attached to that original epic or changeset even when no
     worker is currently active
   - assignee metadata may still help an active runtime notice the message, but
     it is not the durable coordination path
1. If no epic or changeset exists yet, do not use `mail-send` as a durable
   coordination path. Select or create the owning work item first.

## Verification

- Threaded path: message bead exists on the original epic/changeset thread and
  carries explicit work-thread metadata.
- Inactive worker path: the same threaded message is still created on the
  original work item, so a later worker can discover it there.
- Missing-thread path: the script exits with an error instead of creating an
  agent-addressed coordination message.
- Follow `docs/work-threaded-message-migration.md` for planner/worker/operator
  migration guidance.

---
name: mail-send
description: >-
  Send a work-threaded message by creating a message issue with YAML
  frontmatter.
---

# Mail send

Work-threaded messages are the durable coordination path. Use `to` only to
describe the intended audience and, when helpful, to nudge the current runtime.

## Inputs

- subject: Message subject line.
- body: Message body content.
- to: Recipient agent id used to derive audience metadata and optional assignee
  hints.
- from: Sender agent id.
- thread: Optional work thread id (epic or changeset bead id). Required for
  durable work-scoped coordination.
- reply_to: Optional message id being replied to.
- beads_dir: Optional Beads store path.

## Steps

1. Use the dispatch script:
   - `python skills/mail-send/scripts/send_message.py --subject "<subject>" --body "<body>" --to "<to>" --from "<from>" [--thread "<thread>"] [--reply-to "<reply_to>"] [--beads-dir "<beads_dir>"]`
1. For durable work coordination, always provide `--thread <epic-or-changeset>`:
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
1. Use unthreaded messages only when no specific work item exists to carry the
   durable context.

## Verification

- Threaded path: message bead exists on the original epic/changeset thread and
  carries explicit work-thread metadata when `--thread` is provided.
- Inactive worker path: the same threaded message is still created on the
  original work item, so a later worker can discover it there.
- Follow `docs/work-threaded-message-migration.md` for planner/worker/operator
  migration guidance.

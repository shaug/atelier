---
name: mail-send
description: >-
  Send a work-threaded message with compatibility routing to an agent by
  creating a message issue with YAML frontmatter.
---

# Mail send

Work-threaded messages are the durable default. Use `to`/assignee only as a
compatibility routing hint for the currently active runtime.

## Inputs

- subject: Message subject line.
- body: Message body content.
- to: Recipient agent id used for compatibility routing.
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
1. Treat agent-addressed delivery as compatibility routing only:
   - assignee helps the current runtime notice the message
   - thread metadata remains the durable source of truth
1. Do not create planner-to-worker message beads directly with `bd create`.
1. Treat work-threaded delivery as the durable default:
   - when `thread` is present, the script emits work-thread metadata (`thread`,
     `thread_kind`, `audience`, `kind`, `delivery`)
   - assignee-based delivery without a work thread is compatibility routing only
1. The script enforces worker liveness checks:
   - active worker recipient: create an `at:message` bead assigned to `to`
   - inactive worker recipient: create an unassigned executable reroute epic
     (`at:epic`, status `open`) with routing diagnostics
1. Inactive worker reroutes enforce executable-work quality checks on
   `subject`/`body`; low-information placeholders fail closed with deterministic
   diagnostics and a `planner-context: NEEDS-DECISION` hint.

## Verification

- Active recipient path: message bead exists, is assigned to the recipient for
  compatibility routing, and carries explicit work-thread metadata when
  `--thread` is provided.
- Inactive worker path: no worker-targeted message bead is created; reroute epic
  exists with `routing.inactive_worker` and `routing.decision`.
- Follow `docs/work-threaded-message-migration.md` for planner/worker/operator
  migration guidance.

---
name: mail-send
description: >-
  Send a message bead to an agent by creating a message issue with YAML
  frontmatter and assigning it to the recipient.
---

# Mail send

## Inputs

- subject: Message subject line.
- body: Message body content.
- to: Recipient agent id (assignee).
- from: Sender agent id.
- thread: Optional thread id (bead id).
- reply_to: Optional message id being replied to.
- beads_dir: Optional Beads store path.

## Steps

1. Use the dispatch script:
   - `python skills/mail-send/scripts/send_message.py --subject "<subject>" --body "<body>" --to "<to>" --from "<from>" [--thread "<thread>"] [--reply-to "<reply_to>"] [--beads-dir "<beads_dir>"]`
1. Do not create planner-to-worker message beads directly with `bd create`.
1. The script enforces worker liveness checks:
   - active worker recipient: create an `at:message` bead assigned to `to`
   - inactive worker recipient: create an unassigned executable reroute epic
     (`at:epic` + `at:changeset`, status `open`) with routing diagnostics

## Verification

- Active recipient path: message bead exists and is assigned to the recipient.
- Inactive worker path: no worker-targeted message bead is created; reroute epic
  exists with `routing.inactive_worker` and `routing.decision`.

# Work-Threaded Message Migration

Work-threaded messages are the durable coordination model for Atelier. Attach
decisions and instructions to the epic or changeset bead that owns the work so
a later worker or planner session can recover the same context.

Assignees and queues are optional compatibility metadata. They may help the
current runtime notice a message quickly, but they are not a durable
coordination path and must not replace the work thread.

## Default policy

- Put durable coordination on a work thread with `thread: <epic-or-changeset>`.
- Set explicit routing metadata when the message is work-scoped:
  - `thread_target: epic|changeset`
  - `audiences: [worker|planner|operator]`
  - `kind: instruction|notification|needs-decision`
  - `blocking_roles: [worker|planner|operator]` when the message should gate
    execution
- Treat `assignee` and `queue` as compatibility metadata layered on top of the
  work thread, not as the primary source of truth.

## Planner flows

- Planner-to-worker guidance should be threaded to the selected epic or
  changeset.
- Use the worker assignee only as a compatibility nudge for the currently
  active worker session.
- If no worker is active, still persist the message on the same epic or
  changeset thread so the next worker sees the original instruction.

## Worker flows

- Worker `NEEDS-DECISION` and publish/finalize diagnostics should be threaded to
  the affected epic or changeset whenever the decision is about active work.
- Queue metadata may still surface the message in planner/operator startup, but
  the thread owns the durable context.
- Non-work-wide exceptions, such as "no eligible epics", may remain queue-only
  because there is no specific work thread to attach.

## Operator flows

- Operator-required decisions should surface through planner or operator queues
  while still referencing the underlying work thread when one exists.
- Do not route durable work decisions only to a planner process id.

## Compatibility-only cases

Compatibility-only delivery remains acceptable only when one of these is true:

- The message is a transient compatibility nudge layered on top of a threaded
  work message.
- The flow has no specific epic or changeset thread to attach.
- The runtime is claiming a queued message and recording `claimed_by` metadata.

If a work-threaded message contains explicit audience or blocking metadata,
legacy assignee or queue routing must not override it.

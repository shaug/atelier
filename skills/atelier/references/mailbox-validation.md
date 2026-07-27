# Mailbox validation boundary

Issue #775 provides a read-only v1 document boundary. It does not implement a
mailbox transition, Git write, native-ticket mutation, or Atelier mode.

The frozen schema bundle is `mailbox-v1.schema.json`. It defines the complete v1
shapes for:

- `atelier.mailbox/v1`,
- `atelier.project/v1`,
- `atelier.initiative/v1`,
- `atelier.work/v1`, including its claim and acceptance records,
- `atelier.message/v1`,
- `atelier.receipt/v1`,
- and `atelier.project-policy/v1`.

Unknown fields, unsupported versions, malformed identities, path/identity
mismatches, invalid lifecycle combinations, duplicate normative documents,
contradictory cross-document references, dependency cycles, and concurrent
active work for one project fail closed with path-specific diagnostics.
Normative documents use safe YAML 1.2-compatible parsing; duplicate keys,
non-string mapping keys, and unsafe tags are rejected.

A non-null candidate `workspace_id` is an opaque durable host identifier using
only letters, digits, `.`, `_`, `:`, `@`, or `-`. Filesystem paths are invalid.

## Fresh-clone reconstruction

Run:

```text
python3 scripts/mailbox.py reconstruct /path/to/mailbox-clone
```

The helper reads the clone directly and returns one transient
`atelier.mailbox-snapshot/v1` value. It does not write a cache, index, generated
manifest, or projection.

Mailbox documents alone cannot prove current policy, native-ticket, or Agent
Scripts capability state. An approved item therefore does not enter the `ready`
view until the caller supplies all three current gate results:

```json
{
  "wrk_019f9a9e-0000-7000-8000-000000000001": {
    "policy": true,
    "ticket": true,
    "capability": true
  }
}
```

Pass that object with `--readiness /path/to/readiness.json`. Missing or false
gates keep work out of the ready view and produce explicit diagnostics. The
input is invocation-local evidence, not persisted Atelier state.

Validate a managed repository's policy separately:

```text
python3 scripts/mailbox.py validate-policy /path/to/project/.atelier/policy.yaml
```

Both commands are read-only. A successful parse does not authorize or perform
any consequential action.

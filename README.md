# Atelier

Atelier is a workflow framework for development at the speed of accountability.
It keeps durable intent, bounded implementation authority, current evidence, and
human acceptance distinct across agentic tasks.

## Status

This repository is the post-CLI reset scaffold. It contains a valid Codex plugin
manifest and an explicit `/atelier` skill entrypoint, but production `plan`,
`work`, and `audit` behavior is intentionally unavailable.

The first implementation issue is [#774]. Until it lands, invoking Atelier fails
closed without mutating a mailbox, repository, ticket, pull request, or
acceptance record.

## Product boundary

- Atelier is an application built on independently installed Agent Scripts.
- Agent Scripts owns native-ticket implementation and its transitive workflow.
- Atelier owns durable planning, approval, authority fencing, coordination,
  delegated-result validation, live audit, and operator acceptance.
- A passive Git repository is the only Atelier mailbox.
- There is no Beads, Dolt, SQLite, daemon, server, persistent projection,
  backward compatibility, or migration path.

## Repository map

- `.codex-plugin/plugin.json` — Codex plugin manifest
- `skills/atelier/` — explicit skill entrypoint
- `contract_tests/` — executable next-boundary contract
- `docs/` — surviving design and protocol contracts
- `experiments/` — preserved mailbox and composition validation

Read [Atelier as a Skill], the [Git Mailbox Contract], and the
[Implementation Plan] before changing the product boundary.

## Development

```text
just lint
just test
```

The test suite includes one intentional expected failure for the unimplemented
host capability. The reset is healthy when the suite reports that expected
failure and exits successfully.

The final standalone CLI remains recoverable from the immutable
`atelier-cli-v2-final` tag.

<!-- inline reference link definitions. please keep alphabetized -->

[#774]: https://github.com/shaug/atelier/issues/774
[atelier as a skill]: docs/atelier-skill-design.md
[git mailbox contract]: docs/git-mailbox-contract.md
[implementation plan]: docs/implementation-plan.md

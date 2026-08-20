# Atelier

Atelier is a workflow framework for development at the speed of accountability.
It keeps durable intent, bounded implementation authority, current evidence, and
human acceptance distinct across agentic tasks.

## Status

This repository is the post-CLI reset implementation. It contains a valid Codex
plugin, an explicit `/atelier` skill entrypoint, the Codex host boundary, strict
v1 mailbox reconstruction, and verified fast-forward mailbox writes. Production
`plan`, `work`, and `audit` behavior is intentionally unavailable.

Invoking an unavailable mode fails closed without mutating a mailbox,
repository, ticket, pull request, or acceptance record.

## Product boundary

- Atelier is an application built on independently installed Compris.
- Compris owns native-ticket implementation and its transitive workflow.
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
python3 -m pip install --requirement requirements.txt
just lint
just test
```

The test suite includes one intentional expected failure for the unimplemented
host capability. The reset is healthy when the suite reports that expected
failure and exits successfully.

The final standalone CLI remains recoverable from the immutable
`atelier-cli-v2-final` tag.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier as a skill]: docs/atelier-skill-design.md
[git mailbox contract]: docs/git-mailbox-contract.md
[implementation plan]: docs/implementation-plan.md

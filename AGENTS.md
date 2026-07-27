# Atelier — Agent Instructions

This repository defines the skill-based Atelier product. The standalone CLI is
archived at `atelier-cli-v2-final` and must not be restored through
compatibility code.

## Product claim

Atelier exists to support development at the speed of accountability. It keeps
durable intent, delegated implementation, current evidence, and human acceptance
distinct across agentic tasks.

The [Atelier as a Skill], [Git Mailbox Contract], [Project Policy Contract], and
[Implementation Plan] are authoritative.

## Current state

The repository is a reset scaffold. The `/atelier` skill is discoverable but
production `plan`, `work`, and `audit` modes are not implemented. The open
native issue graph beginning at #772 defines implementation order.

Do not claim unavailable behavior or emulate it with ad hoc orchestration.

## Architecture boundaries

- Codex is the v0 reference host.
- The Git mailbox is Atelier's only shared state.
- Native tickets describe project work.
- Agent Scripts is an independently installed platform dependency.
- Agent Scripts owns ticket implementation and its transitive workflow.
- Atelier owns approved intent, project policy, authority fencing, durable
  coordination, terminal validation, audit, and operator acceptance.
- Delivery, acceptance, merge, deployment, and native-ticket completion are
  distinct events.

Do not add Beads, Dolt, SQLite, a daemon, a server, a persistent projection,
backward compatibility, or a migration reader.

## Repository shape

- `.codex-plugin/plugin.json` is the plugin manifest.
- `skills/atelier/` is the only production skill entrypoint.
- `contract_tests/` defines the next honest implementation boundary.
- `scripts/validate_repository.py` validates the reset shape.
- `docs/` contains only surviving product doctrine and contracts.
- `experiments/` contains the preserved mailbox and composition evidence.

Add product code only when an approved graph issue requires it. Keep each change
independently reviewable and avoid building later graph nodes early.

## Authority

Implementation authority does not imply merge, deployment, issue closure,
acceptance, or cleanup authority. Every consequential external mutation must be
explicitly granted and revalidated against current state.

## Quality gates

Run:

```text
just lint
just test
```

The expected-failure contract test is intentional. It names the missing `HOST`
capability and must become an ordinary passing test when #774 implements that
contract.

## Commits and publication

Use Conventional Commits:

```text
<type>(<scope>): <imperative subject>
```

Include a body that summarizes the complete commit. Run the quality gates before
committing and pushing. Publish changes through a pull request; do not merge
without explicit authority.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier as a skill]: docs/atelier-skill-design.md
[git mailbox contract]: docs/git-mailbox-contract.md
[implementation plan]: docs/implementation-plan.md
[project policy contract]: docs/project-policy-contract.md

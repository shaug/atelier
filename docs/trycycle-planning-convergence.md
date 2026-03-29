# Trycycle Planning Convergence

This document records how trycycle planning behavior converges into Atelier's
native `planning` and `refine-plan` skills while preserving Atelier persistence
contracts.

## Source inventory

The convergence references these trycycle sources.

- `subskills/trycycle-planning/SKILL.md`
- `subagents/prompt-planning-initial.md`
- `subagents/prompt-planning-edit.md`
- `orchestrator/run_phase.py`
- `orchestrator/prompt_builder/build.py`
- `orchestrator/prompt_builder/template_ast.py`
- `orchestrator/prompt_builder/validate_rendered.py`

## Doctrine mapping

The baseline planning doctrine is extracted into Atelier `planning`.

- `subskills/trycycle-planning/SKILL.md`: Mapped to `planning`
  - Anchor: `Strategy Gate (before task breakdown)`
  - Anchor: `Low bar for changing direction.`
  - Anchor: `High bar for stopping to ask the user.`
  - Anchor: `Bite-Sized Task Granularity`
  - Anchor: `Completion Standard`
- `subagents/prompt-planning-initial.md`: Mapped to `planning`
  - Anchor: request framing and planning ownership language.
- `subagents/prompt-planning-edit.md`: Mapped to `planning`
  - Anchor: judgment and proportional edit/rewrite expectations.

## Mechanics mapping

The iterative loop mechanics are extracted into `refine-plan`.

- `subagents/prompt-planning-initial.md`: Mapped to `refine-plan`
  - Anchor:

    ```text
    Task:
    - Review the `trycycle-planning` skill
    ```

  - Anchor: `## Plan verdict`
- `subagents/prompt-planning-edit.md`: Mapped to `refine-plan`
  - Anchor: `REVISED`
  - Anchor: `READY`
- `orchestrator/run_phase.py`: Mapped to `refine-plan`
  - Anchor: `_prepare_phase`
  - Anchor: `_command_run`
  - Anchor: `prompt_builder`
- `orchestrator/prompt_builder/build.py`: Mapped to `refine-plan`
  - Anchor: render and placeholder-binding contract.
- `orchestrator/prompt_builder/template_ast.py`: Mapped to `refine-plan`
  - Anchor: prompt-template parsing contract.
- `orchestrator/prompt_builder/validate_rendered.py`: Mapped to `refine-plan`
  - Anchor: fail-closed rendered prompt validation contract.

## Atelier adaptation rationale

- Atelier stores authoritative refinement state in bead notes rather than
  ephemeral process memory.
- Doctrine (`planning`) and mechanism (`refine-plan`) are split to keep
  non-iterative planning clear and reusable.
- Worker claimability gates derive from persisted verdict and approval evidence,
  not transient planner output.
- Convergence keeps trycycle's strategic tone while adapting boundary contracts
  to Atelier's Beads-backed persistence model.

## Non-goals

- Replacing Atelier's Beads store or introducing a separate planner state
  service.
- Auto-enabling refinement for all work items without explicit activation.
- Inferring approval from prose-only notes.
- Coupling unrefined claimability behavior to refinement-only guardrails.

See [Atelier Behavior and Design Notes] for the user-visible behavior contract.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier behavior and design notes]: ./behavior.md

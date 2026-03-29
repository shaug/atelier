# prompt-planning-initial.md

- Review the `trycycle-planning` skill.
- Use the `trycycle-planning` skill to produce a complete implementation plan.
- Return `## Plan verdict` with `CREATED`.

# prompt-planning-edit.md

- Diagnose the plan completely.
- Return `## Plan verdict` with `REVISED` or `READY`.

# orchestrator/run_phase.py

- \_prepare_phase
- \_command_run
- prompt_builder

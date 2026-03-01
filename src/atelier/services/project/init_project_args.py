from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InitProjectArgs:
    """Typed inputs for project initialization orchestration.

    Attributes:
        branch_prefix: Optional branch prefix override for generated worktrees.
        branch_pr_mode: Optional PR mode override for new changesets.
        branch_history: Optional git history mode override.
        branch_squash_message: Optional squash commit message policy override.
        branch_pr_strategy: Optional PR sequencing strategy override.
        agent: Optional default agent override.
        editor_edit: Optional editor command for editing flows.
        editor_work: Optional editor command for workspace operations.
        yes: Whether interactive prompts should be skipped.
    """

    branch_prefix: str | None = None
    branch_pr_mode: str | None = None
    branch_history: str | None = None
    branch_squash_message: str | None = None
    branch_pr_strategy: str | None = None
    agent: str | None = None
    editor_edit: str | None = None
    editor_work: str | None = None
    yes: bool = False

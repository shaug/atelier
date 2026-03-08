"""Worker prompt rendering helpers."""

from __future__ import annotations

from .. import workspace


def worker_opening_prompt(
    *,
    project_enlistment: str,
    workspace_branch: str,
    epic_id: str,
    changeset_id: str,
    changeset_title: str,
    merge_conflict: bool = False,
    review_feedback: bool = False,
    review_pr_url: str | None = None,
) -> str:
    """Build the initial worker prompt passed to agent runtimes."""
    session = workspace.workspace_session_identifier(
        project_enlistment, workspace_branch, changeset_id or None
    )
    title = changeset_title.strip() if changeset_title else ""
    summary = f"{changeset_id}: {title}" if title else changeset_id
    lines = [
        session,
        ("Execute only this assigned changeset and do not ask for task clarification."),
        f"Epic: {epic_id}",
        f"Changeset: {summary}",
        (
            "Before any commit/push/publish attempt, run a north-star "
            "self-review against the assigned bead acceptance criteria."
        ),
        (
            "Append a `north_star_review.<timestamp>:` note to the changeset "
            "bead before first push with unmet_acceptance_criteria, "
            "required_code_changes_per_criterion, implementation_summary, "
            "and a completion_checklist citing commit/file evidence."
        ),
        (
            "Role boundary: implement only committable changeset artifacts "
            "(code/config/docs/tests) for the assigned changeset."
        ),
        (
            "Do not treat comment closure alone as completion; finish only "
            "when the full bead goal is implemented or send NEEDS-DECISION."
        ),
        (
            "Do not promote, clean up, or otherwise mutate sibling/unclaimed "
            "work beads; planner owns non-commit orchestration."
        ),
        (
            "If this project uses PR review and PR creation is allowed now, create "
            "or update the PR during finalize."
        ),
        (
            "PR title/body must be user-facing and based on ticket scope + "
            "acceptance criteria; do not mention internal bead IDs."
        ),
        (
            "Do not set status=closed while PR lifecycle is active "
            "(`pushed`,`draft-pr`,`pr-open`,`in-review`,`approved`). "
            "Close only when PR is terminal (`merged`/`closed`) or non-PR "
            "integration proof exists (`changeset.integrated_sha`)."
        ),
        (
            "Do not commit/push/publish while unmet acceptance criteria "
            "remain or the completion checklist is incomplete."
        ),
        (
            "When done, update beads status/metadata for this changeset and required "
            "ancestor lifecycle state only. If blocked, send NEEDS-DECISION with "
            "details and exit."
        ),
    ]
    if merge_conflict:
        lines.extend(
            [
                "",
                "Priority mode: merge-conflict",
                (
                    "This run is for default-branch merge conflict resolution on "
                    "the assigned changeset PR."
                ),
                (
                    "Rebase onto the default branch (or merge default branch), "
                    "resolve conflicts, push the updated branch, then re-run review checks."
                ),
                (
                    "If mergeability signals remain UNKNOWN/transient, report the "
                    "exact signal values and retry guidance."
                ),
            ]
        )
    if review_feedback:
        lines.extend(
            [
                "",
                "Priority mode: review-feedback",
                (
                    "This run is for PR feedback resolution. Before fetching or "
                    "addressing PR comments, re-read the seeded epic and "
                    "changeset beads and confirm scope, non-goals, acceptance "
                    "criteria, and done definition."
                ),
                (
                    "After that bead-first review, fetch open PR feedback "
                    "comments and address them directly without narrowing the "
                    "goal to comment closure alone."
                ),
                (
                    "For inline review comments, reply inline to each comment and "
                    "resolve the same thread; do not create new top-level PR "
                    "comments as a substitute."
                ),
                (
                    "Use github-prs skill scripts list_review_threads.py and "
                    "reply_inline_thread.py for deterministic inline handling."
                ),
                (
                    "Do not create local pr-* branches for temporary PR inspection. "
                    "Use detached commits or refs/atelier/review/* refs and clean "
                    "them up after use."
                ),
                ("Do not mark this changeset complete while review feedback remains unaddressed."),
            ]
        )
        if review_pr_url:
            lines.append(f"PR: {review_pr_url}")
    return "\n".join(lines)

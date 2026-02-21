"""Branch/publish/integration helpers for worker finalization flows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import agents, beads, codex, exec, git, worktrees
from . import integration as worker_integration
from .models import PublishSignalDiagnostics


def normalize_branch_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def extract_changeset_root_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return normalize_branch_value(fields.get("changeset.root_branch"))


def extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return normalize_branch_value(fields.get("workspace.parent_branch"))


def branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    return worker_integration.branch_ref_for_lookup(repo_root, branch, git_path=git_path)


def epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    return worker_integration.epic_root_integrated_into_parent(
        epic_issue,
        repo_root=repo_root,
        extract_changeset_root_branch=extract_changeset_root_branch,
        extract_workspace_parent_branch=extract_workspace_parent_branch,
        git_path=git_path,
    )


def changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    lookup_pr_payload: Callable[[str | None, str], dict[str, object] | None],
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    return worker_integration.changeset_integration_signal(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=lookup_pr_payload,
        git_path=git_path,
    )


def ensure_local_branch(branch: str, *, repo_root: Path, git_path: str | None = None) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if git.git_ref_exists(repo_root, f"refs/heads/{branch_name}", git_path=git_path):
        return True
    if not git.git_ref_exists(repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path):
        return False
    result = exec.try_run_command(
        git.git_command(
            [
                "-C",
                str(repo_root),
                "branch",
                branch_name,
                f"origin/{branch_name}",
            ],
            git_path=git_path,
        )
    )
    return bool(result and result.returncode == 0)


def run_git_status(
    args: list[str],
    *,
    repo_root: Path,
    git_path: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    target_cwd = cwd or repo_root
    result = exec.try_run_command(
        git.git_command(["-C", str(target_cwd), *args], git_path=git_path)
    )
    if result is None:
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"command failed: git {' '.join(args)}"
    return True, (result.stdout or "").strip()


def resolve_epic_integration_cwd(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    root_branch: str,
    git_path: str | None = None,
) -> Path:
    if project_data_dir is None or not epic_id:
        return repo_root
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None or not mapping.worktree_path:
        return repo_root
    worktree_path = Path(mapping.worktree_path)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return repo_root
    current_branch = git.git_current_branch(worktree_path, git_path=git_path)
    if current_branch == root_branch:
        return worktree_path
    return repo_root


def resolve_changeset_worktree_path(
    *,
    project_data_dir: Path | None,
    epic_id: str,
    changeset_id: str,
) -> Path | None:
    if project_data_dir is None or not epic_id or not changeset_id:
        return None
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None:
        return None
    relpath = mapping.changeset_worktrees.get(changeset_id)
    if not relpath:
        return None
    worktree_path = Path(relpath)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return None
    return worktree_path


def collect_publish_signal_diagnostics(
    *,
    work_branch: str,
    epic_id: str,
    changeset_id: str,
    project_data_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
) -> PublishSignalDiagnostics:
    local_branch_exists = git.git_ref_exists(
        repo_root, f"refs/heads/{work_branch}", git_path=git_path
    )
    remote_branch_exists = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    worktree_path = resolve_changeset_worktree_path(
        project_data_dir=project_data_dir,
        epic_id=epic_id,
        changeset_id=changeset_id,
    )
    status_root = worktree_path or repo_root
    dirty_entries = tuple(git.git_status_porcelain(status_root, git_path=git_path))
    return PublishSignalDiagnostics(
        local_branch_exists=local_branch_exists,
        remote_branch_exists=remote_branch_exists,
        worktree_path=worktree_path,
        dirty_entries=dirty_entries,
    )


def attempt_push_work_branch(
    work_branch: str, *, repo_root: Path, git_path: str | None = None
) -> tuple[bool, str]:
    if not git.git_ref_exists(repo_root, f"refs/heads/{work_branch}", git_path=git_path):
        return False, f"local branch missing: {work_branch}"
    ok, detail = run_git_status(
        ["push", "-u", "origin", work_branch], repo_root=repo_root, git_path=git_path
    )
    if ok:
        return True, detail or f"pushed {work_branch} to origin"
    return False, detail


def format_publish_diagnostics(
    diagnostics: PublishSignalDiagnostics, *, push_detail: str | None = None
) -> str:
    lines = [
        f"- local branch exists: {'yes' if diagnostics.local_branch_exists else 'no'}",
        f"- remote branch exists: {'yes' if diagnostics.remote_branch_exists else 'no'}",
    ]
    if diagnostics.worktree_path is not None:
        lines.append(f"- changeset worktree: {diagnostics.worktree_path}")
    if diagnostics.dirty_entries:
        lines.append("- dirty files:")
        for entry in diagnostics.dirty_entries[:8]:
            lines.append(f"  - {entry}")
        if len(diagnostics.dirty_entries) > 8:
            lines.append(f"  - ... (+{len(diagnostics.dirty_entries) - 8} more)")
    if push_detail:
        lines.append(f"- push attempt: {push_detail}")
    return "\n".join(lines)


def ensure_branch_not_checked_out(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> None:
    current = git.git_current_branch(repo_root, git_path=git_path)
    if current != branch:
        return
    run_git_status(["checkout", "--detach"], repo_root=repo_root, git_path=git_path)


def sync_local_branch_from_remote(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if not git.git_ref_exists(repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path):
        return False
    ensure_branch_not_checked_out(branch_name, repo_root=repo_root, git_path=git_path)
    ok, _ = run_git_status(
        ["branch", "-f", branch_name, f"origin/{branch_name}"],
        repo_root=repo_root,
        git_path=git_path,
    )
    return ok


def first_external_ticket_id(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    tickets = beads.parse_external_tickets(description if isinstance(description, str) else None)
    if not tickets:
        return None
    primary = [ticket for ticket in tickets if ticket.relation == "primary"]
    source = primary or tickets
    for ticket in source:
        ticket_id = (ticket.ticket_id or "").strip()
        if ticket_id:
            return ticket_id
    return None


def squash_subject(issue: dict[str, object], epic_id: str) -> str:
    ticket_id = first_external_ticket_id(issue)
    title = str(issue.get("title") or "").strip()
    if ticket_id and title:
        return f"{ticket_id}: {title}"
    if ticket_id:
        return ticket_id
    if title:
        return title
    return epic_id


def normalize_squash_message_mode(value: object) -> str:
    if not isinstance(value, str):
        return "deterministic"
    normalized = value.strip().lower()
    if normalized in {"deterministic", "agent"}:
        return normalized
    return "deterministic"


def parse_squash_subject_output(output: str) -> str | None:
    cleaned = codex.strip_ansi(output).replace("\r", "\n")
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"thinking", "user", "assistant", "codex", "--------"}:
            continue
        if lowered.startswith(
            (
                "warning:",
                "deprecated:",
                "mcp:",
                "tokens used",
                "openai codex",
                "session id:",
            )
        ):
            continue
        line = line.strip("`\"'").strip()
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        line = " ".join(line.split())
        if line:
            return line[:120]
    return None


def agent_generated_squash_subject(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    repo_root: Path,
    git_path: str | None,
    agent_spec: agents.AgentSpec | None,
    agent_options: list[str] | None,
    agent_home: Path | None,
    agent_env: dict[str, str] | None,
    with_codex_exec: Callable[[list[str], str], list[str]],
    strip_flag_with_value: Callable[[list[str], str], list[str]],
    ensure_exec_subcommand_flag: Callable[[list[str], str], list[str]],
) -> str | None:
    if agent_spec is None or agent_home is None:
        return None
    if agent_spec.name != "codex":
        return None

    commit_messages = git.git_commit_messages(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    files_changed = git.git_diff_name_status(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    ticket_id = first_external_ticket_id(epic_issue) or "none"
    title = str(epic_issue.get("title") or epic_id).strip() or epic_id
    commits_preview = (
        "\n".join(f"- {message}" for message in commit_messages[:12] if message) or "- (none)"
    )
    files_preview = "\n".join(f"- {entry}" for entry in files_changed[:30] if entry) or ("- (none)")
    prompt_text = "\n".join(
        [
            "Draft a single git squash commit subject for integrating an epic branch.",
            "",
            "Constraints:",
            "- Output exactly one line (no markdown, no bullets, no quotes).",
            "- Imperative mood, no trailing period.",
            "- Maximum 72 characters.",
            "",
            f"Epic id: {epic_id}",
            f"Primary ticket: {ticket_id}",
            f"Epic title: {title}",
            f"Parent branch: {parent_branch}",
            f"Root branch: {root_branch}",
            "",
            "Commit messages being squashed:",
            commits_preview,
            "",
            "Changed files:",
            files_preview,
            "",
            "Return only the commit subject.",
        ]
    )

    start_cmd, start_cwd = agent_spec.build_start_command(
        agent_home,
        list(agent_options or []),
        prompt_text,
    )
    start_cmd = with_codex_exec(start_cmd, prompt_text)
    start_cmd = strip_flag_with_value(start_cmd, "--cd")
    start_cmd = ensure_exec_subcommand_flag(start_cmd, "--skip-git-repo-check")
    start_cwd = agent_home
    result = exec.try_run_command(start_cmd, cwd=start_cwd, env=agent_env)
    if result is None or result.returncode != 0:
        return None
    parsed = parse_squash_subject_output(result.stdout or "")
    if parsed:
        return parsed
    return parse_squash_subject_output(result.stderr or "")


def cleanup_epic_branches_and_worktrees(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    keep_branches: set[str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    worker_integration.cleanup_epic_branches_and_worktrees(
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        epic_id=epic_id,
        keep_branches=keep_branches,
        git_path=git_path,
        log=log,
        run_git_status=run_git_status,
    )


def integrate_epic_root_to_parent(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    history: str,
    squash_message_mode: str = "deterministic",
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    integration_cwd: Path | None = None,
    repo_root: Path,
    git_path: str | None = None,
    with_codex_exec: Callable[[list[str], str], list[str]] | None = None,
    strip_flag_with_value: Callable[[list[str], str], list[str]] | None = None,
    ensure_exec_subcommand_flag: Callable[[list[str], str], list[str]] | None = None,
) -> tuple[bool, str | None, str | None]:
    return worker_integration.integrate_epic_root_to_parent(
        epic_issue=epic_issue,
        epic_id=epic_id,
        root_branch=root_branch,
        parent_branch=parent_branch,
        history=history,
        squash_message_mode=squash_message_mode,
        squash_message_agent_spec=squash_message_agent_spec,
        squash_message_agent_options=squash_message_agent_options,
        squash_message_agent_home=squash_message_agent_home,
        squash_message_agent_env=squash_message_agent_env,
        integration_cwd=integration_cwd,
        repo_root=repo_root,
        git_path=git_path,
        ensure_local_branch=ensure_local_branch,
        run_git_status=run_git_status,
        sync_local_branch_from_remote=sync_local_branch_from_remote,
        normalize_squash_message_mode=normalize_squash_message_mode,
        agent_generated_squash_subject=(
            lambda **kwargs: agent_generated_squash_subject(
                **kwargs,
                with_codex_exec=with_codex_exec or (lambda cmd, _prompt: cmd),
                strip_flag_with_value=(strip_flag_with_value or (lambda args, _flag: args)),
                ensure_exec_subcommand_flag=(
                    ensure_exec_subcommand_flag or (lambda args, _flag: args)
                ),
            )
        ),
        squash_subject=squash_subject,
    )

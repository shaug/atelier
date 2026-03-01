"""Worker branch integration and cleanup helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator

from .. import agents, beads, exec, git, worktrees

INTEGRATED_SHA_NOTE_PATTERN = re.compile(
    r"`?changeset\.integrated_sha`?\s*[:=]\s*([0-9a-fA-F]{7,40})\b",
    re.MULTILINE,
)

RunGitStatusFn = Callable[..., tuple[bool, str | None]]


def _normalize_branch_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _root_integrated_into_parent(
    *,
    fields: dict[str, str],
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    root_branch = _normalize_branch_field(fields.get("changeset.root_branch"))
    if not root_branch:
        return False, None
    parent_branch = _normalize_branch_field(fields.get("changeset.parent_branch"))
    workspace_parent = _normalize_branch_field(fields.get("workspace.parent_branch"))
    if not parent_branch:
        parent_branch = workspace_parent
    if not parent_branch or parent_branch == root_branch:
        default_branch = _normalize_branch_field(
            git.git_default_branch(repo_root, git_path=git_path)
        )
        if default_branch:
            parent_branch = default_branch
    if not parent_branch or parent_branch == root_branch:
        return False, None
    root_ref = branch_ref_for_lookup(repo_root, root_branch, git_path=git_path)
    parent_ref = branch_ref_for_lookup(repo_root, parent_branch, git_path=git_path)
    if not root_ref or not parent_ref:
        return False, None
    is_ancestor = git.git_is_ancestor(repo_root, root_ref, parent_ref, git_path=git_path)
    if is_ancestor is True:
        return True, git.git_rev_parse(repo_root, root_ref, git_path=git_path)
    fully_applied = git.git_branch_fully_applied(repo_root, parent_ref, root_ref, git_path=git_path)
    if fully_applied is True:
        return True, git.git_rev_parse(repo_root, root_ref, git_path=git_path)
    return False, None


def _integration_target_branches(
    fields: dict[str, str],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> list[str]:
    root_branch = _normalize_branch_field(fields.get("changeset.root_branch"))
    candidates: list[str] = []

    def add_candidate(value: object) -> None:
        normalized = _normalize_branch_field(value)
        if not normalized:
            return
        if root_branch and normalized == root_branch:
            return
        if normalized not in candidates:
            candidates.append(normalized)

    add_candidate(fields.get("changeset.parent_branch"))
    add_candidate(fields.get("workspace.parent_branch"))
    add_candidate(git.git_default_branch(repo_root, git_path=git_path))
    return candidates


def _target_refs_for_branch(
    repo_root: Path,
    branch: str,
    *,
    git_path: str | None = None,
    require_remote_tracking: bool = False,
) -> list[str]:
    normalized = branch.strip()
    if not normalized:
        return []
    resolved = branch_ref_for_lookup(repo_root, normalized, git_path=git_path)
    if not resolved:
        return []

    remote_ref = f"origin/{normalized}"
    if resolved == remote_ref:
        return [remote_ref]

    refs: list[str] = []
    if resolved == normalized:
        remote_exists = git.git_ref_exists(
            repo_root,
            f"refs/remotes/{remote_ref}",
            git_path=git_path,
        )
        if remote_exists:
            return [remote_ref]
        if require_remote_tracking:
            return []
        refs.append(normalized)
        return refs

    refs.append(resolved)
    return refs


def _target_refs_for_branches(
    repo_root: Path,
    branches: list[str],
    *,
    git_path: str | None = None,
    require_remote_tracking: bool = False,
) -> list[str]:
    refs: list[str] = []
    for branch in branches:
        for ref in _target_refs_for_branch(
            repo_root,
            branch,
            git_path=git_path,
            require_remote_tracking=require_remote_tracking,
        ):
            if ref not in refs:
                refs.append(ref)
    return refs


def _refresh_origin_refs(repo_root: Path, *, git_path: str | None = None) -> bool:
    result = exec.try_run_command(
        git.git_command(
            ["-C", str(repo_root), "fetch", "--no-tags", "origin"],
            git_path=git_path,
        )
    )
    return bool(result and result.returncode == 0)


def branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    normalized = branch.strip()
    if not normalized:
        return None
    if git_path is None:
        local_exists = git.git_ref_exists(repo_root, f"refs/heads/{normalized}")
    else:
        local_exists = git.git_ref_exists(repo_root, f"refs/heads/{normalized}", git_path=git_path)
    if local_exists:
        return normalized
    if git_path is None:
        remote_exists = git.git_ref_exists(repo_root, f"refs/remotes/origin/{normalized}")
    else:
        remote_exists = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path
        )
    if remote_exists:
        return f"origin/{normalized}"
    return None


def epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    extract_changeset_root_branch: Callable[[dict[str, object]], str | None],
    extract_workspace_parent_branch: Callable[[dict[str, object]], str | None],
    git_path: str | None = None,
) -> bool:
    root_branch = beads.extract_workspace_root_branch(epic_issue)
    if not root_branch:
        root_branch = extract_changeset_root_branch(epic_issue)
    parent_branch = extract_workspace_parent_branch(epic_issue)
    default_branch = git.git_default_branch(repo_root, git_path=git_path)
    if not parent_branch or (root_branch and parent_branch == root_branch):
        parent_branch = default_branch or parent_branch or root_branch
    if not root_branch or not parent_branch:
        return False
    parent_ref = branch_ref_for_lookup(repo_root, parent_branch, git_path=git_path)
    if not parent_ref:
        return False
    root_ref = branch_ref_for_lookup(repo_root, root_branch, git_path=git_path)
    if not root_ref:
        return True
    is_ancestor = git.git_is_ancestor(repo_root, root_ref, parent_ref, git_path=git_path)
    if is_ancestor is True:
        return True
    fully_applied = git.git_branch_fully_applied(repo_root, parent_ref, root_ref, git_path=git_path)
    return fully_applied is True


def changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    lookup_pr_payload: Callable[[str | None, str], dict[str, object] | None],
    git_path: str | None = None,
    require_target_branch_proof: bool = False,
) -> tuple[bool, str | None]:
    description = issue.get("description")
    description_text = description if isinstance(description, str) else ""
    notes = issue.get("notes")
    notes_text = notes if isinstance(notes, str) else ""
    fields = beads.parse_description_fields(description_text)
    integrated_sha_candidates: list[str] = []
    integrated_sha = fields.get("changeset.integrated_sha")
    if integrated_sha and integrated_sha.strip().lower() != "null":
        integrated_sha_candidates.append(integrated_sha.strip())
    combined_text = "\n".join(part for part in (description_text, notes_text) if part)
    if combined_text:
        integrated_sha_candidates.extend(
            match.group(1) for match in INTEGRATED_SHA_NOTE_PATTERN.finditer(combined_text)
        )
    root_branch = _normalize_branch_field(fields.get("changeset.root_branch"))
    work_branch = _normalize_branch_field(fields.get("changeset.work_branch"))

    if require_target_branch_proof:
        target_branches = _integration_target_branches(
            fields,
            repo_root=repo_root,
            git_path=git_path,
        )
        target_refs = _target_refs_for_branches(
            repo_root,
            target_branches,
            git_path=git_path,
            require_remote_tracking=True,
        )
        source_branches: list[str] = []
        for branch in (work_branch, root_branch):
            if branch and branch not in source_branches:
                source_branches.append(branch)

        def source_refs_for_branches() -> list[str]:
            refs: list[str] = []
            for source_branch in source_branches:
                source_ref = branch_ref_for_lookup(repo_root, source_branch, git_path=git_path)
                if source_ref and source_ref not in refs:
                    refs.append(source_ref)
            return refs

        source_refs = source_refs_for_branches()

        def prove_against_targets(current_target_refs: list[str]) -> tuple[bool, str | None]:
            if integrated_sha_candidates and current_target_refs:
                for candidate in reversed(integrated_sha_candidates):
                    candidate_sha = git.git_rev_parse(repo_root, candidate, git_path=git_path)
                    if not candidate_sha:
                        continue
                    if source_refs and not any(
                        git.git_is_ancestor(repo_root, candidate_sha, source_ref, git_path=git_path)
                        is True
                        for source_ref in source_refs
                    ):
                        continue
                    for ref in current_target_refs:
                        if (
                            git.git_is_ancestor(repo_root, candidate_sha, ref, git_path=git_path)
                            is True
                        ):
                            return True, candidate_sha
            if not current_target_refs or not source_refs:
                return False, None
            for source_ref in source_refs:
                source_sha = git.git_rev_parse(repo_root, source_ref, git_path=git_path)
                for target_ref in current_target_refs:
                    if (
                        git.git_is_ancestor(repo_root, source_ref, target_ref, git_path=git_path)
                        is True
                    ):
                        return True, source_sha
                    if (
                        git.git_branch_fully_applied(
                            repo_root, target_ref, source_ref, git_path=git_path
                        )
                        is True
                    ):
                        return True, source_sha
            return False, None

        proven, integrated_sha = prove_against_targets(target_refs)
        if proven:
            return True, integrated_sha
        if target_branches and _refresh_origin_refs(repo_root, git_path=git_path):
            refreshed_target_refs = _target_refs_for_branches(
                repo_root,
                target_branches,
                git_path=git_path,
                require_remote_tracking=True,
            )
            source_refs = source_refs_for_branches()
            proven, integrated_sha = prove_against_targets(refreshed_target_refs)
            if proven:
                return True, integrated_sha
        if repo_slug and work_branch:
            lookup_pr_payload(repo_slug, work_branch)
        return False, None

    candidate_refs: list[str] = []
    for key in (
        "changeset.root_branch",
        "changeset.parent_branch",
        "workspace.parent_branch",
    ):
        value = fields.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized.lower() == "null":
            continue
        if normalized not in candidate_refs:
            candidate_refs.append(normalized)
    if integrated_sha_candidates:
        for candidate in reversed(integrated_sha_candidates):
            candidate_sha = git.git_rev_parse(repo_root, candidate, git_path=git_path)
            if not candidate_sha:
                continue
            for ref_name in candidate_refs:
                ref = branch_ref_for_lookup(repo_root, ref_name, git_path=git_path)
                if not ref:
                    continue
                if git.git_is_ancestor(repo_root, candidate_sha, ref, git_path=git_path) is True:
                    return True, candidate_sha

    if repo_slug and work_branch:
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        if pr_payload and pr_payload.get("mergedAt"):
            return True, None

    if not root_branch or not work_branch:
        return False, None

    if root_branch == work_branch:
        return _root_integrated_into_parent(fields=fields, repo_root=repo_root, git_path=git_path)
    root_ref = branch_ref_for_lookup(repo_root, root_branch, git_path=git_path)
    work_ref = branch_ref_for_lookup(repo_root, work_branch, git_path=git_path)
    if not root_ref or not work_ref:
        return False, None

    is_ancestor = git.git_is_ancestor(repo_root, work_ref, root_ref, git_path=git_path)
    if is_ancestor is True:
        return True, git.git_rev_parse(repo_root, root_ref, git_path=git_path)

    fully_applied = git.git_branch_fully_applied(repo_root, root_ref, work_ref, git_path=git_path)
    if fully_applied is True:
        return True, git.git_rev_parse(repo_root, root_ref, git_path=git_path)
    return False, None


def cleanup_epic_branches_and_worktrees(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    keep_branches: set[str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
    run_git_status: RunGitStatusFn,
) -> None:
    keep = {branch for branch in (keep_branches or set()) if branch}
    if project_data_dir is None:
        if log:
            log(f"cleanup skip: {epic_id} (project data dir unavailable)")
        return
    mapping_path = worktrees.mapping_path(project_data_dir, epic_id)
    mapping = worktrees.load_mapping(mapping_path)
    if mapping is None:
        if log:
            log(f"cleanup skip: {epic_id} (no worktree mapping)")
        return

    relpaths = sorted(
        {
            relpath
            for relpath in [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            if relpath
        }
    )
    for relpath in relpaths:
        worktree_path = project_data_dir / relpath
        if not worktree_path.exists():
            if log:
                log(f"cleanup skip worktree: {worktree_path} (missing)")
            continue
        if not (worktree_path / ".git").exists():
            if log:
                log(f"cleanup skip worktree: {worktree_path} (not a git worktree)")
            continue
        if log:
            log(f"cleanup remove worktree: {worktree_path}")
        ok, detail = run_git_status(
            ["worktree", "remove", "--force", str(worktree_path)],
            repo_root=repo_root,
            git_path=git_path,
        )
        if log:
            if ok:
                log(f"cleanup removed worktree: {worktree_path}")
            else:
                log(f"cleanup failed worktree: {worktree_path} ({detail})")

    branches = {mapping.root_branch, *mapping.changesets.values()}
    for branch in branches:
        if not branch or branch in keep:
            if log and branch:
                log(f"cleanup keep branch: {branch}")
            continue
        if log:
            log(f"cleanup delete remote branch: origin/{branch}")
        remote_ok, remote_detail = run_git_status(
            ["push", "origin", "--delete", branch],
            repo_root=repo_root,
            git_path=git_path,
        )
        if log:
            if remote_ok:
                log(f"cleanup deleted remote branch: origin/{branch}")
            else:
                log(f"cleanup remote branch skip/fail: origin/{branch} ({remote_detail})")
        if log:
            log(f"cleanup delete local branch: {branch}")
        local_ok, local_detail = run_git_status(
            ["branch", "-D", branch], repo_root=repo_root, git_path=git_path
        )
        if log:
            if local_ok:
                log(f"cleanup deleted local branch: {branch}")
            else:
                log(f"cleanup local branch skip/fail: {branch} ({local_detail})")

    mapping_path.unlink(missing_ok=True)
    if log:
        log(f"cleanup removed mapping: {mapping_path}")


def integrate_epic_root_to_parent(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    history: str,
    squash_message_mode: str,
    squash_message_agent_spec: agents.AgentSpec | None,
    squash_message_agent_options: list[str] | None,
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    integration_cwd: Path | None,
    repo_root: Path,
    git_path: str | None,
    ensure_local_branch: Callable[..., bool],
    run_git_status: RunGitStatusFn,
    sync_local_branch_from_remote: Callable[..., bool],
    normalize_squash_message_mode: Callable[[str | None], str],
    agent_generated_squash_subject: Callable[..., str | None],
    squash_subject: Callable[[dict[str, object], str], str],
) -> tuple[bool, str | None, str | None]:
    root = root_branch.strip()
    parent = parent_branch.strip()
    if not root or not parent:
        return False, None, "missing root/parent branch metadata"
    if parent == root:
        return True, git.git_rev_parse(repo_root, root, git_path=git_path), None
    if not ensure_local_branch(root, repo_root=repo_root, git_path=git_path):
        return False, None, f"root branch {root!r} not found"
    if not ensure_local_branch(parent, repo_root=repo_root, git_path=git_path):
        return False, None, f"parent branch {parent!r} not found"

    operation_cwd = integration_cwd or repo_root
    clean = git.git_is_clean(operation_cwd, git_path=git_path)
    if clean is False:
        return False, None, "repository must be clean before epic finalization"

    for attempt in range(2):
        parent_head = git.git_rev_parse(repo_root, parent, git_path=git_path)
        if not parent_head:
            return False, None, f"failed to resolve parent branch head for {parent!r}"

        is_ancestor = git.git_is_ancestor(repo_root, root, parent, git_path=git_path)
        if is_ancestor is True:
            return True, parent_head, None
        fully_applied = git.git_branch_fully_applied(repo_root, parent, root, git_path=git_path)
        if fully_applied is True:
            return True, parent_head, None

        can_ff = git.git_is_ancestor(repo_root, parent, root, git_path=git_path) is True

        if history == "rebase":
            rebase_args = ["rebase", parent, root]
            if operation_cwd != repo_root:
                current_branch = git.git_current_branch(operation_cwd, git_path=git_path)
                if current_branch == root:
                    rebase_args = ["rebase", parent]
            ok, detail = run_git_status(
                rebase_args,
                repo_root=repo_root,
                git_path=git_path,
                cwd=operation_cwd,
            )
            if not ok:
                run_git_status(
                    ["rebase", "--abort"],
                    repo_root=repo_root,
                    git_path=git_path,
                    cwd=operation_cwd,
                )
                return False, None, detail or f"failed to rebase {root} onto {parent}"
            new_head = git.git_rev_parse(repo_root, root, git_path=git_path)
            if not new_head:
                return False, None, f"failed to resolve rebased head for {root!r}"
            ok, detail = run_git_status(
                ["update-ref", f"refs/heads/{parent}", new_head, parent_head],
                repo_root=repo_root,
                git_path=git_path,
            )
            if not ok:
                if attempt == 0 and sync_local_branch_from_remote(
                    parent, repo_root=repo_root, git_path=git_path
                ):
                    continue
                return False, None, detail or "parent branch moved during finalization"
            ok, detail = run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return True, new_head, None
            if attempt == 0 and sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        if history == "merge":
            if can_ff:
                new_head = git.git_rev_parse(repo_root, root, git_path=git_path)
                if not new_head:
                    return False, None, f"failed to resolve head for {root!r}"
                ok, detail = run_git_status(
                    ["update-ref", f"refs/heads/{parent}", new_head, parent_head],
                    repo_root=repo_root,
                    git_path=git_path,
                )
                if not ok:
                    if attempt == 0 and sync_local_branch_from_remote(
                        parent, repo_root=repo_root, git_path=git_path
                    ):
                        continue
                    return (
                        False,
                        None,
                        detail or "parent branch moved during finalization",
                    )
            else:
                current = git.git_current_branch(repo_root, git_path=git_path)
                ok, detail = run_git_status(
                    ["checkout", parent], repo_root=repo_root, git_path=git_path
                )
                if not ok:
                    return False, None, detail
                ok, detail = run_git_status(
                    ["merge", "--no-edit", root], repo_root=repo_root, git_path=git_path
                )
                if current and current != parent:
                    run_git_status(["checkout", current], repo_root=repo_root, git_path=git_path)
                if not ok:
                    run_git_status(["merge", "--abort"], repo_root=repo_root, git_path=git_path)
                    return (
                        False,
                        None,
                        detail or f"failed to merge {root} into {parent}",
                    )
            ok, detail = run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return (
                    True,
                    git.git_rev_parse(repo_root, parent, git_path=git_path),
                    None,
                )
            if attempt == 0 and sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        if history == "squash":
            current = git.git_current_branch(repo_root, git_path=git_path)
            ok, detail = run_git_status(
                ["checkout", parent], repo_root=repo_root, git_path=git_path
            )
            if not ok:
                return False, None, detail
            ok, detail = run_git_status(
                ["merge", "--squash", root], repo_root=repo_root, git_path=git_path
            )
            if not ok:
                run_git_status(["merge", "--abort"], repo_root=repo_root, git_path=git_path)
                if current and current != parent:
                    run_git_status(["checkout", current], repo_root=repo_root, git_path=git_path)
                return (
                    False,
                    None,
                    detail or f"failed to squash-merge {root} into {parent}",
                )
            message = squash_subject(epic_issue, epic_id)
            if normalize_squash_message_mode(squash_message_mode) == "agent":
                drafted = agent_generated_squash_subject(
                    epic_issue=epic_issue,
                    epic_id=epic_id,
                    root_branch=root,
                    parent_branch=parent,
                    repo_root=repo_root,
                    git_path=git_path,
                    agent_spec=squash_message_agent_spec,
                    agent_options=squash_message_agent_options,
                    agent_home=squash_message_agent_home,
                    agent_env=squash_message_agent_env,
                )
                if drafted:
                    message = drafted
            with _temporary_text_file(message) as message_file:
                ok, detail = run_git_status(
                    ["commit", "-F", str(message_file)],
                    repo_root=repo_root,
                    git_path=git_path,
                )
            if current and current != parent:
                run_git_status(["checkout", current], repo_root=repo_root, git_path=git_path)
            if not ok:
                run_git_status(["merge", "--abort"], repo_root=repo_root, git_path=git_path)
                return (
                    False,
                    None,
                    detail or f"failed to create squash commit on {parent}",
                )
            ok, detail = run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return (
                    True,
                    git.git_rev_parse(repo_root, parent, git_path=git_path),
                    None,
                )
            if attempt == 0 and sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        return False, None, f"unsupported branch.history value: {history!r}"

    return False, None, "epic finalization failed after retry"


@contextmanager
def _temporary_text_file(content: str) -> Iterator[Path]:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)

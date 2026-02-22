"""Worktree and changeset mapping helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import exec as exec_util
from . import git, paths
from .io import die

METADATA_DIRNAME = ".meta"


@dataclass(frozen=True)
class WorktreeMapping:
    epic_id: str
    worktree_path: str
    root_branch: str
    changesets: dict[str, str]
    changeset_worktrees: dict[str, str]


def worktrees_root(project_dir: Path) -> Path:
    """Return the root directory for worktrees."""
    return paths.project_worktrees_dir(project_dir)


def worktree_dir(project_dir: Path, epic_id: str) -> Path:
    """Return the worktree directory for an epic."""
    return worktrees_root(project_dir) / epic_id


def mapping_path(project_dir: Path, epic_id: str) -> Path:
    """Return the mapping file path for an epic worktree."""
    return worktrees_root(project_dir) / METADATA_DIRNAME / f"{epic_id}.json"


def load_mapping(path: Path) -> WorktreeMapping | None:
    """Load a worktree mapping from disk."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    epic_id = payload.get("epic_id")
    worktree_path = payload.get("worktree_path")
    root_branch = payload.get("root_branch")
    changesets = payload.get("changesets")
    changeset_worktrees = payload.get("changeset_worktrees")
    if not isinstance(epic_id, str) or not epic_id:
        return None
    if not isinstance(worktree_path, str) or not worktree_path:
        return None
    if not isinstance(root_branch, str):
        root_branch = ""
    if not isinstance(changesets, dict):
        changesets = {}
    if not isinstance(changeset_worktrees, dict):
        changeset_worktrees = {}
    normalized = {
        str(key): str(value)
        for key, value in changesets.items()
        if key is not None and value is not None
    }
    normalized_worktrees = {
        str(key): str(value)
        for key, value in changeset_worktrees.items()
        if key is not None and value is not None
    }
    return WorktreeMapping(
        epic_id=epic_id,
        worktree_path=worktree_path,
        root_branch=root_branch,
        changesets=normalized,
        changeset_worktrees=normalized_worktrees,
    )


def write_mapping(path: Path, mapping: WorktreeMapping) -> None:
    """Write a worktree mapping to disk."""
    payload = {
        "epic_id": mapping.epic_id,
        "worktree_path": mapping.worktree_path,
        "root_branch": mapping.root_branch,
        "changesets": mapping.changesets,
        "changeset_worktrees": mapping.changeset_worktrees,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _worktree_branch_in_use(
    repo_root: Path, branch_ref: str, *, git_path: str | None = None
) -> bool:
    cmd = git.git_command(
        ["-C", str(repo_root), "worktree", "list", "--porcelain"],
        git_path=git_path,
    )
    result = exec_util.try_run_command(cmd)
    if result is None or result.returncode != 0:
        return False
    raw = result.stdout or ""
    for line in raw.splitlines():
        if not line.startswith("branch "):
            continue
        ref = line.split(" ", 1)[1].strip()
        if ref == branch_ref:
            return True
    return False


def _ensure_root_branch_exists(
    repo_root: Path, root_branch: str, *, git_path: str | None = None
) -> None:
    root_ref = f"refs/heads/{root_branch}"
    if git.git_ref_exists(repo_root, root_ref, git_path=git_path):
        return

    remote_root_ref = f"refs/remotes/origin/{root_branch}"
    if git.git_ref_exists(repo_root, remote_root_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                [
                    "-C",
                    str(repo_root),
                    "branch",
                    "--track",
                    root_branch,
                    f"origin/{root_branch}",
                ],
                git_path=git_path,
            )
        )
        return

    default_branch = git.git_default_branch(repo_root, git_path=git_path)
    if not default_branch:
        die("failed to determine default branch for worktree")
    local_default_ref = f"refs/heads/{default_branch}"
    remote_default_ref = f"refs/remotes/origin/{default_branch}"
    if git.git_ref_exists(repo_root, local_default_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                [
                    "-C",
                    str(repo_root),
                    "branch",
                    root_branch,
                    default_branch,
                ],
                git_path=git_path,
            )
        )
        return
    if git.git_ref_exists(repo_root, remote_default_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                [
                    "-C",
                    str(repo_root),
                    "branch",
                    root_branch,
                    f"origin/{default_branch}",
                ],
                git_path=git_path,
            )
        )
        return
    die(f"default branch {default_branch!r} not found for worktree")


def _resolve_mapping_worktree_path(project_dir: Path, mapping: WorktreeMapping) -> Path:
    mapped = Path(mapping.worktree_path)
    if mapped.is_absolute():
        return mapped
    return project_dir / mapped


def _branch_exists(repo_root: Path, branch: str, *, git_path: str | None = None) -> bool:
    local_ref = f"refs/heads/{branch}"
    if git.git_ref_exists(repo_root, local_ref, git_path=git_path):
        return True
    remote_ref = f"refs/remotes/origin/{branch}"
    return git.git_ref_exists(repo_root, remote_ref, git_path=git_path)


def _checkout_branch_for_mapping_migration(
    worktree_path: Path,
    root_branch: str,
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> None:
    local_ref = f"refs/heads/{root_branch}"
    remote_ref = f"refs/remotes/origin/{root_branch}"
    if git.git_ref_exists(repo_root, local_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                ["-C", str(worktree_path), "checkout", root_branch],
                git_path=git_path,
            )
        )
        return
    if git.git_ref_exists(repo_root, remote_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                [
                    "-C",
                    str(worktree_path),
                    "checkout",
                    "-B",
                    root_branch,
                    f"origin/{root_branch}",
                ],
                git_path=git_path,
            )
        )
        return
    die(
        "worktree mapping migration blocked: "
        f"target root branch {root_branch!r} not found locally or on origin."
    )


def reconcile_worktree_mapping_root_branch(
    project_dir: Path,
    epic_id: str,
    *,
    current_mapping: WorktreeMapping,
    expected_root_branch: str,
    repo_root: Path,
    git_path: str | None = None,
) -> WorktreeMapping:
    """Reconcile a stale mapping root branch when migration is deterministic."""
    old_root = current_mapping.root_branch.strip()
    new_root = expected_root_branch.strip()
    if not old_root or old_root == new_root:
        return current_mapping

    mapped_path = _resolve_mapping_worktree_path(project_dir, current_mapping)
    if mapped_path.exists():
        if not (mapped_path / ".git").exists():
            die(
                "worktree mapping migration blocked: "
                f"{mapped_path} exists but is not a git worktree. "
                "Fix the path or remove stale mapping metadata before retrying."
            )
        current_branch = git.git_current_branch(mapped_path, git_path=git_path)
        if not current_branch or current_branch == "HEAD":
            die(
                "worktree mapping migration blocked: "
                f"unable to resolve current branch for {mapped_path}. "
                "Checkout a branch manually, then rerun."
            )
        if current_branch == old_root:
            status = git.git_status_porcelain(mapped_path, git_path=git_path)
            if status:
                die(
                    "worktree mapping migration blocked: "
                    f"{mapped_path} has local changes on {old_root!r}. "
                    "Commit/stash/discard changes, then rerun."
                )
            if not _branch_exists(repo_root, new_root, git_path=git_path):
                die(
                    "worktree mapping migration blocked: "
                    f"target root branch {new_root!r} does not exist "
                    f"(current mapping root is {old_root!r})."
                )
            _checkout_branch_for_mapping_migration(
                mapped_path,
                new_root,
                repo_root=repo_root,
                git_path=git_path,
            )
        elif current_branch != new_root:
            die(
                "worktree mapping migration blocked: "
                f"{mapped_path} is on {current_branch!r}, expected {old_root!r} "
                f"or {new_root!r}. Resolve branch state manually, then rerun."
            )

    updated_changesets = dict(current_mapping.changesets)
    if updated_changesets.get(epic_id) == old_root:
        updated_changesets[epic_id] = new_root
    updated = WorktreeMapping(
        epic_id=current_mapping.epic_id,
        worktree_path=current_mapping.worktree_path,
        root_branch=new_root,
        changesets=updated_changesets,
        changeset_worktrees=current_mapping.changeset_worktrees,
    )
    write_mapping(mapping_path(project_dir, epic_id), updated)
    return updated


def ensure_worktree_mapping(
    project_dir: Path,
    epic_id: str,
    root_branch: str,
    *,
    repo_root: Path | None = None,
    git_path: str | None = None,
) -> WorktreeMapping:
    """Ensure a worktree mapping exists and return it."""
    if not epic_id:
        die("epic id must not be empty")
    if not root_branch:
        die("root branch must not be empty")
    root = worktrees_root(project_dir)
    paths.ensure_dir(root)
    path = mapping_path(project_dir, epic_id)
    paths.ensure_dir(path.parent)
    mapping = load_mapping(path)
    if mapping is not None:
        if mapping.root_branch and mapping.root_branch != root_branch:
            if repo_root is None:
                die(
                    "root branch does not match existing worktree mapping "
                    f"({mapping.root_branch!r} != {root_branch!r}) and no "
                    "repository context is available for reconciliation"
                )
            mapping = reconcile_worktree_mapping_root_branch(
                project_dir,
                epic_id,
                current_mapping=mapping,
                expected_root_branch=root_branch,
                repo_root=repo_root,
                git_path=git_path,
            )
        if not mapping.root_branch:
            updated = WorktreeMapping(
                epic_id=mapping.epic_id,
                worktree_path=mapping.worktree_path,
                root_branch=root_branch,
                changesets=mapping.changesets,
                changeset_worktrees=mapping.changeset_worktrees,
            )
            write_mapping(path, updated)
            return updated
        return mapping
    relative_path = f"{paths.WORKTREES_DIRNAME}/{epic_id}"
    mapping = WorktreeMapping(
        epic_id=epic_id,
        worktree_path=relative_path,
        root_branch=root_branch,
        changesets={},
        changeset_worktrees={},
    )
    write_mapping(path, mapping)
    return mapping


def derive_changeset_branch(root_branch: str, changeset_id: str) -> str:
    """Derive a deterministic branch name for a changeset bead."""
    if not root_branch or not changeset_id:
        die("root branch and changeset id must not be empty")
    return f"{root_branch}-{changeset_id}"


def ensure_changeset_branch(
    project_dir: Path,
    epic_id: str,
    changeset_id: str,
    *,
    root_branch: str,
    repo_root: Path | None = None,
    git_path: str | None = None,
) -> tuple[str, WorktreeMapping]:
    """Ensure a changeset branch mapping exists and return it."""
    mapping = ensure_worktree_mapping(
        project_dir,
        epic_id,
        root_branch,
        repo_root=repo_root,
        git_path=git_path,
    )
    branch = mapping.changesets.get(changeset_id)
    if branch:
        return branch, mapping
    if changeset_id == epic_id:
        # Epic-as-changeset runs execute directly on the epic root branch.
        branch = root_branch
    else:
        branch = derive_changeset_branch(root_branch, changeset_id)
    updated = WorktreeMapping(
        epic_id=mapping.epic_id,
        worktree_path=mapping.worktree_path,
        root_branch=mapping.root_branch,
        changesets={**mapping.changesets, changeset_id: branch},
        changeset_worktrees=mapping.changeset_worktrees,
    )
    write_mapping(mapping_path(project_dir, epic_id), updated)
    return branch, updated


def changeset_worktree_relpath(changeset_id: str) -> str:
    """Return the default worktree path for a changeset."""
    if not changeset_id:
        die("changeset id must not be empty")
    return f"{paths.WORKTREES_DIRNAME}/{changeset_id}"


def ensure_changeset_worktree(
    project_dir: Path,
    repo_root: Path,
    epic_id: str,
    changeset_id: str,
    *,
    branch: str,
    root_branch: str,
    parent_branch: str | None = None,
    git_path: str | None = None,
) -> Path:
    """Ensure a git worktree exists for a changeset and return its path."""
    if not branch or not root_branch:
        die("changeset branch and root branch must not be empty")
    mapping = ensure_worktree_mapping(
        project_dir,
        epic_id,
        root_branch,
        repo_root=repo_root,
        git_path=git_path,
    )
    relpath = mapping.changeset_worktrees.get(changeset_id)
    if not relpath:
        relpath = changeset_worktree_relpath(changeset_id)
        updated = WorktreeMapping(
            epic_id=mapping.epic_id,
            worktree_path=mapping.worktree_path,
            root_branch=mapping.root_branch,
            changesets=mapping.changesets,
            changeset_worktrees={**mapping.changeset_worktrees, changeset_id: relpath},
        )
        write_mapping(mapping_path(project_dir, epic_id), updated)
        mapping = updated

    worktree_path = project_dir / relpath
    if worktree_path.exists():
        if (worktree_path / ".git").exists():
            return worktree_path
        die(f"worktree path exists but is not a git worktree: {worktree_path}")

    branch_ref = f"refs/heads/{branch}"
    remote_branch = f"refs/remotes/origin/{branch}"
    root_ref = f"refs/heads/{root_branch}"
    remote_root = f"refs/remotes/origin/{root_branch}"

    parent = (parent_branch or "").strip() or root_branch
    parent_ref = f"refs/heads/{parent}"
    remote_parent = f"refs/remotes/origin/{parent}"

    if git.git_ref_exists(repo_root, branch_ref, git_path=git_path):
        args = ["-C", str(repo_root), "worktree", "add", str(worktree_path), branch]
    elif git.git_ref_exists(repo_root, remote_branch, git_path=git_path):
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            f"origin/{branch}",
        ]
    elif git.git_ref_exists(repo_root, parent_ref, git_path=git_path):
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            parent,
        ]
    elif git.git_ref_exists(repo_root, remote_parent, git_path=git_path):
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            f"origin/{parent}",
        ]
    elif git.git_ref_exists(repo_root, root_ref, git_path=git_path):
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            root_branch,
        ]
    elif git.git_ref_exists(repo_root, remote_root, git_path=git_path):
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            f"origin/{root_branch}",
        ]
    else:
        die(f"root branch {root_branch!r} not found for changeset worktree")

    exec_util.run_command(git.git_command(args, git_path=git_path))
    return worktree_path


def ensure_changeset_checkout(
    worktree_path: Path,
    branch: str,
    *,
    root_branch: str,
    parent_branch: str | None = None,
    git_path: str | None = None,
) -> None:
    """Ensure the changeset branch exists and is checked out in the worktree."""
    if not branch or not root_branch:
        die("changeset branch and root branch must not be empty")
    if not worktree_path.exists():
        die("worktree path missing; run 'atelier work' first")
    if not (worktree_path / ".git").exists():
        die("worktree path is not a git worktree")

    default_branch = git.git_default_branch(worktree_path, git_path=git_path)
    if not default_branch:
        die("failed to determine default branch for worktree")

    root_ref = f"refs/heads/{root_branch}"
    if not git.git_ref_exists(worktree_path, root_ref, git_path=git_path):
        remote_root = f"refs/remotes/origin/{root_branch}"
        if git.git_ref_exists(worktree_path, remote_root, git_path=git_path):
            exec_util.run_command(
                git.git_command(
                    [
                        "-C",
                        str(worktree_path),
                        "checkout",
                        "-b",
                        root_branch,
                        "--track",
                        f"origin/{root_branch}",
                    ],
                    git_path=git_path,
                )
            )
        else:
            exec_util.run_command(
                git.git_command(
                    [
                        "-C",
                        str(worktree_path),
                        "checkout",
                        "-b",
                        root_branch,
                        default_branch,
                    ],
                    git_path=git_path,
                )
            )

    branch_ref = f"refs/heads/{branch}"
    if git.git_ref_exists(worktree_path, branch_ref, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                ["-C", str(worktree_path), "checkout", branch],
                git_path=git_path,
            )
        )
        return

    remote_branch = f"refs/remotes/origin/{branch}"
    if git.git_ref_exists(worktree_path, remote_branch, git_path=git_path):
        exec_util.run_command(
            git.git_command(
                [
                    "-C",
                    str(worktree_path),
                    "checkout",
                    "-b",
                    branch,
                    "--track",
                    f"origin/{branch}",
                ],
                git_path=git_path,
            )
        )
        return

    parent = (parent_branch or "").strip() or root_branch
    parent_ref = f"refs/heads/{parent}"
    remote_parent = f"refs/remotes/origin/{parent}"

    exec_util.run_command(
        git.git_command(
            [
                "-C",
                str(worktree_path),
                "checkout",
                "-b",
                branch,
                parent
                if git.git_ref_exists(worktree_path, parent_ref, git_path=git_path)
                else (
                    f"origin/{parent}"
                    if git.git_ref_exists(worktree_path, remote_parent, git_path=git_path)
                    else root_branch
                ),
            ],
            git_path=git_path,
        )
    )


def ensure_git_worktree(
    project_dir: Path,
    repo_root: Path,
    epic_id: str,
    *,
    root_branch: str,
    git_path: str | None = None,
) -> Path:
    """Ensure a git worktree exists for the epic and return its path."""
    mapping = ensure_worktree_mapping(
        project_dir,
        epic_id,
        root_branch,
        repo_root=repo_root,
        git_path=git_path,
    )
    _ensure_root_branch_exists(repo_root, root_branch, git_path=git_path)
    worktree_path = project_dir / mapping.worktree_path
    if worktree_path.exists():
        if (worktree_path / ".git").exists():
            return worktree_path
        die(f"worktree path exists but is not a git worktree: {worktree_path}")

    root_ref = f"refs/heads/{root_branch}"
    in_use = _worktree_branch_in_use(repo_root, root_ref, git_path=git_path)
    if in_use:
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--detach",
            str(worktree_path),
            root_branch,
        ]
    else:
        args = [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            str(worktree_path),
            root_branch,
        ]

    exec_util.run_command(git.git_command(args, git_path=git_path))
    return worktree_path


def remove_git_worktree(
    project_dir: Path,
    repo_root: Path,
    epic_id: str,
    *,
    git_path: str | None = None,
    force: bool = False,
) -> bool:
    """Remove the git worktree for an epic, returning true if removed."""
    mapping = load_mapping(mapping_path(project_dir, epic_id))
    if mapping is None:
        return False
    worktree_path = project_dir / mapping.worktree_path
    if not worktree_path.exists():
        return False
    if not (worktree_path / ".git").exists():
        die(f"worktree path is not a git worktree: {worktree_path}")

    args = ["-C", str(repo_root), "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    exec_util.run_command(git.git_command(args, git_path=git_path))
    return True

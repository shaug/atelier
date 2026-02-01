import json
import tempfile
from pathlib import Path

import atelier.worktrees as worktrees


def test_derive_changeset_branch_from_hierarchy() -> None:
    assert worktrees.derive_changeset_branch("epic", "epic.2") == "epic-2"


def test_ensure_changeset_branch_writes_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        branch, mapping = worktrees.ensure_changeset_branch(
            project_dir, "epic", "epic.1"
        )
        assert branch == "epic-1"
        mapping_file = worktrees.mapping_path(project_dir, "epic")
        assert mapping_file.exists()
        payload = json.loads(mapping_file.read_text(encoding="utf-8"))
        assert payload["epic_id"] == "epic"
        assert payload["changesets"]["epic.1"] == "epic-1"
        assert mapping.worktree_path == "worktrees/epic"

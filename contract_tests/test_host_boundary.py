"""Executable contract for the Codex host boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
HOST_CAPABILITY = ROOT / "skills" / "atelier" / "references" / "host-capability.json"
OBSERVATION_SCHEMA = ROOT / "skills" / "atelier" / "references" / "github-observation.schema.json"
HOST_BOUNDARY_MODULE = ROOT / "skills" / "atelier" / "scripts" / "host_boundary.py"
REQUIRED_OPERATIONS = [
    "github.issue.read",
    "github.issue.relationships.read",
    "github.pull-request.read",
    "github.pull-request.comments.read",
    "github.pull-request.reviews.read",
    "github.pull-request.checks.read",
    "github.pull-request.threads.read",
]
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
AUTHORITY_ACTIONS = [
    "repository.candidate.create",
    "repository.candidate.push",
    "pull_request.create",
    "pull_request.update",
    "review.reply",
    "review.resolve",
]


def load_host_boundary() -> ModuleType:
    """Load the skill-local helper without making the skill a Python package."""
    spec = importlib.util.spec_from_file_location("atelier_host_boundary", HOST_BOUNDARY_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host boundary helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST_BOUNDARY = load_host_boundary()


def write_json(path: Path, value: object) -> None:
    """Write one deterministic test fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    """Hash one fixture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def issue_reference(number: int) -> dict[str, object]:
    """Return one normalized native issue reference."""
    return {
        "id": f"issue-{number}",
        "number": number,
        "title": f"Issue {number}",
        "state": "OPEN",
        "url": f"https://github.com/shaug/atelier/issues/{number}",
    }


def comment(identifier: str) -> dict[str, object]:
    """Return one normalized comment."""
    return {
        "id": identifier,
        "author": "reviewer",
        "body": "Evidence.",
        "created_at": "2026-07-27T03:00:00Z",
        "updated_at": "2026-07-27T03:00:00Z",
        "url": f"https://github.com/shaug/atelier/{identifier}",
    }


def complete_observation() -> dict[str, object]:
    """Return a complete exact-candidate observation."""
    issue = issue_reference(774)
    issue.update(
        {
            "body": "Discover the host boundary.",
            "updated_at": "2026-07-27T03:00:00Z",
            "parent": issue_reference(772),
            "sub_issues": [],
            "blocked_by": [issue_reference(773)],
            "blocking": [issue_reference(777)],
        }
    )
    return {
        "schema": "atelier.github-observation/v1",
        "observed_at": "2026-07-27T03:00:00Z",
        "repository": {
            "id": "repository-atelier",
            "name_with_owner": "shaug/atelier",
            "url": "https://github.com/shaug/atelier",
        },
        "issue": issue,
        "issue_comments": [],
        "pull_request": {
            "id": "pull-request-785",
            "number": 785,
            "title": "Discover the Codex host boundary",
            "body": "Fixes #774",
            "url": "https://github.com/shaug/atelier/pull/785",
            "state": "OPEN",
            "is_draft": False,
            "merged": False,
            "mergeable": "MERGEABLE",
            "merge_state_status": "CLEAN",
            "review_decision": None,
            "base": {
                "repository": "shaug/atelier",
                "ref": "refs/heads/main",
                "sha": BASE_SHA,
            },
            "head": {
                "repository": "shaug/atelier",
                "ref": "refs/heads/scott/issue-774-host-boundary",
                "sha": HEAD_SHA,
            },
            "updated_at": "2026-07-27T03:00:00Z",
        },
        "pull_request_comments": [comment("comment-1")],
        "reviews": [
            {
                "id": "review-1",
                "pull_request_number": 785,
                "author": "reviewer",
                "state": "APPROVED",
                "body": "Looks good.",
                "submitted_at": "2026-07-27T03:00:00Z",
                "commit_sha": HEAD_SHA,
                "url": "https://github.com/shaug/atelier/pull/785#review-1",
            }
        ],
        "checks": [
            {
                "id": "check-1",
                "pull_request_number": 785,
                "kind": "CHECK_RUN",
                "name": "test",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "candidate_sha": HEAD_SHA,
                "details_url": "https://github.com/shaug/atelier/actions/runs/1",
            }
        ],
        "threads": [
            {
                "id": "thread-1",
                "pull_request_number": 785,
                "is_resolved": True,
                "is_outdated": False,
                "path": "skills/atelier/SKILL.md",
                "line": 20,
                "start_line": None,
                "comments": [comment("thread-comment-1")],
            }
        ],
        "completeness": {
            "issue": True,
            "issue_comments": True,
            "issue_relationships": True,
            "pull_request": True,
            "pull_request_comments": True,
            "reviews": True,
            "checks": True,
            "threads": True,
        },
    }


class HostBoundaryContract(unittest.TestCase):
    """Define the production boundary implemented by issue 774."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.skill_root = self.root / "installed-implement-ticket"
        capability_root = self.skill_root / "references" / "delegated-execution"
        capability_root.mkdir(parents=True)

        self.skill_file = self.skill_root / "SKILL.md"
        self.skill_file.write_text(
            "---\nname: implement-ticket\ndescription: fixture\n---\n",
            encoding="utf-8",
        )
        for name in (
            "CONTRACT.md",
            "checkpoint-request.schema.json",
            "checkpoint-response.schema.json",
            "result.schema.json",
        ):
            path = capability_root / name
            if name.endswith(".json"):
                write_json(path, {"type": "object"})
            else:
                path.write_text("# Contract\n", encoding="utf-8")
        write_json(
            capability_root / "invocation.schema.json",
            {
                "type": "object",
                "$defs": {"action": {"enum": AUTHORITY_ACTIONS}},
            },
        )
        validator = capability_root / "validate.py"
        validator.write_text(
            "import json, sys\n"
            "value = json.load(open(sys.argv[2], encoding='utf-8'))\n"
            "raise SystemExit(0 if value.get('id') == "
            "'agent-scripts.implement-ticket/delegated-execution/v1' else 1)\n",
            encoding="utf-8",
        )
        manifest = {
            "schema": "agent-scripts.implement-ticket/capability-manifest/v1",
            "id": "agent-scripts.implement-ticket/delegated-execution/v1",
            "contract": "CONTRACT.md",
            "invocation_schema": "invocation.schema.json",
            "checkpoint_request_schema": "checkpoint-request.schema.json",
            "checkpoint_response_schema": "checkpoint-response.schema.json",
            "result_schema": "result.schema.json",
            "validator": "validate.py",
            "terminal_states": ["ready_pr", "blocked", "requires_epic"],
            "checkpoint_phases": ["pre_external_mutation", "candidate_published"],
        }
        self.manifest_path = capability_root / "capability.json"
        write_json(self.manifest_path, manifest)

        self.schema_path = self.root / "github-observation.schema.json"
        write_json(self.schema_path, {"type": "object"})
        descriptor = {
            "schema": "atelier.host-capability/v1",
            "reference_host": "codex",
            "delegated_capability": ("agent-scripts.implement-ticket/delegated-execution/v1"),
            "delegated_authority_actions": AUTHORITY_ACTIONS,
            "accepted_terminal_states": ["ready_pr", "blocked", "requires_epic"],
            "delegated_skill": {
                "stable_name": "agent-scripts:implement-ticket",
                "frontmatter_name": "implement-ticket",
                "skill_sha256": sha256(self.skill_file),
                "capability_manifest": ("references/delegated-execution/capability.json"),
                "capability_manifest_sha256": sha256(self.manifest_path),
            },
            "native_state": {
                "access": "read-only",
                "connector": "github@openai-curated",
                "observation_schema": self.schema_path.name,
                "required_operations": REQUIRED_OPERATIONS,
            },
            "native_state_access": "read-only",
            "fallback_to_copied_workflows": False,
        }
        self.descriptor_path = self.root / "host-capability.json"
        write_json(self.descriptor_path, descriptor)

    def check_host(self, *, operations: list[str] | None = None) -> dict[str, object]:
        """Run the fixture host check."""
        return HOST_BOUNDARY.check_host(
            descriptor_path=self.descriptor_path,
            skill_name="agent-scripts:implement-ticket",
            skill_root=self.skill_root,
            connector="github@openai-curated",
            operations=REQUIRED_OPERATIONS if operations is None else operations,
        )

    def write_observation(self, value: dict[str, object]) -> Path:
        """Write one observation fixture."""
        path = self.root / "observation.json"
        write_json(path, value)
        return path

    def test_host_capability_is_published(self) -> None:
        """Require a versioned, fail-closed host capability descriptor."""
        payload = json.loads(HOST_CAPABILITY.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "atelier.host-capability/v1")
        self.assertEqual(payload["reference_host"], "codex")
        self.assertEqual(
            payload["delegated_capability"],
            "agent-scripts.implement-ticket/delegated-execution/v1",
        )
        self.assertEqual(payload["native_state_access"], "read-only")
        self.assertFalse(payload["fallback_to_copied_workflows"])
        self.assertEqual(
            payload["delegated_skill"]["stable_name"],
            "agent-scripts:implement-ticket",
        )
        self.assertEqual(payload["delegated_authority_actions"], AUTHORITY_ACTIONS)
        self.assertEqual(
            payload["native_state"]["required_operations"],
            REQUIRED_OPERATIONS,
        )
        self.assertIsInstance(
            json.loads(OBSERVATION_SCHEMA.read_text(encoding="utf-8")),
            dict,
        )

    def test_exact_dependency_and_read_operations_pass(self) -> None:
        """Accept only the exact skill, manifest, connector, and read surface."""
        result = self.check_host()
        self.assertEqual(result["status"], "compatible")
        self.assertEqual(result["native_state_access"], "read-only")

    def test_missing_read_operation_fails_closed(self) -> None:
        """Reject a host that cannot provide one required observation category."""
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "github.pull-request.threads.read",
        ):
            self.check_host(operations=REQUIRED_OPERATIONS[:-1])

    def test_changed_installed_skill_fails_closed(self) -> None:
        """Reject a same-named but content-mismatched installed skill."""
        self.skill_file.write_text(
            self.skill_file.read_text(encoding="utf-8") + "\nchanged\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "installed skill hash mismatch",
        ):
            self.check_host()

    def test_missing_capability_schema_fails_closed(self) -> None:
        """Reject a manifest whose versioned protocol is incomplete."""
        (self.manifest_path.parent / "result.schema.json").unlink()
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "result_schema missing",
        ):
            self.check_host()

    def test_missing_authority_action_fails_closed(self) -> None:
        """Reject a dependency that cannot enforce the approved v0 vocabulary."""
        write_json(
            self.manifest_path.parent / "invocation.schema.json",
            {
                "type": "object",
                "$defs": {"action": {"enum": AUTHORITY_ACTIONS[:-1]}},
            },
        )
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "review.resolve",
        ):
            self.check_host()

    def test_complete_native_observation_passes(self) -> None:
        """Accept complete issue, PR, review, check, and thread evidence."""
        observation = complete_observation()
        result = HOST_BOUNDARY.validate_observation(self.write_observation(observation))
        self.assertEqual(result["pull_request"]["head"]["sha"], HEAD_SHA)

    def test_unknown_observation_field_fails_closed(self) -> None:
        """Reject provider drift rather than silently ignoring unknown state."""
        observation = complete_observation()
        observation["unexpected"] = True
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            r"\$\.unexpected: unknown property",
        ):
            HOST_BOUNDARY.validate_observation(self.write_observation(observation))

    def test_check_candidate_mismatch_fails_closed(self) -> None:
        """Bind check observations to the exact pull-request head."""
        observation = complete_observation()
        observation["checks"][0]["candidate_sha"] = "c" * 40
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "candidate SHA mismatch",
        ):
            HOST_BOUNDARY.validate_observation(self.write_observation(observation))

    def test_incomplete_pagination_fails_closed(self) -> None:
        """Reject a partial collection even when its visible items are valid."""
        observation = complete_observation()
        observation["completeness"]["threads"] = False
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            r"\$\.completeness\.threads: expected constant True",
        ):
            HOST_BOUNDARY.validate_observation(self.write_observation(observation))

    def test_pull_request_collections_require_pull_request_identity(self) -> None:
        """Do not accept orphaned review evidence."""
        observation = complete_observation()
        observation["pull_request"] = None
        with self.assertRaisesRegex(
            HOST_BOUNDARY.HostBoundaryError,
            "collections require pull_request identity",
        ):
            HOST_BOUNDARY.validate_observation(self.write_observation(observation))


if __name__ == "__main__":
    unittest.main()

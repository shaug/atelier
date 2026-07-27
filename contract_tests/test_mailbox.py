"""Executable contract for strict v1 mailbox reconstruction."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAILBOX_MODULE = ROOT / "skills" / "atelier" / "scripts" / "mailbox.py"
MAILBOX_SCHEMA = ROOT / "skills" / "atelier" / "references" / "mailbox-v1.schema.json"
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "sha256:" + "c" * 64
TIMESTAMP = "2026-07-27T12:00:00Z"
EVIDENCE = [
    "candidate-remote-reachable",
    "pull-request-head-current",
    "pull-request-open",
    "pull-request-mergeable",
    "required-checks-pass",
    "required-validation-reported",
    "independent-review-current",
    "unresolved-feedback-zero",
]
AUTHORITY = [
    "repository.candidate.create",
    "repository.candidate.push",
    "pull_request.create",
    "pull_request.update",
    "review.reply",
    "review.resolve",
]


def load_mailbox() -> ModuleType:
    spec = importlib.util.spec_from_file_location("atelier_mailbox", MAILBOX_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load mailbox helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAILBOX = load_mailbox()


def git_run(cwd: Path | None, *arguments: str) -> None:
    environment = os.environ.copy()
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_PREFIX",
    ):
        environment.pop(name, None)
    subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def identifier(prefix: str, number: int) -> str:
    return f"{prefix}_019f9a9e-0000-7000-8000-{number:012x}"


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, dict | list) and child:
                lines.append(f"{prefix}{key}:")
                lines.extend(yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {scalar(child)}")
        return lines
    if isinstance(value, list):
        lines = []
        for child in value:
            if isinstance(child, dict | list):
                lines.append(f"{prefix}-")
                lines.extend(yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}- {scalar(child)}")
        return lines
    raise TypeError(f"cannot encode {type(value)}")


def yaml_text(value: dict[str, Any]) -> str:
    return "\n".join(yaml_lines(value)) + "\n"


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text(value), encoding="utf-8")


def write_markdown(path: Path, value: dict[str, Any], body: str = "Fixture.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml_text(value)}---\n{body}", encoding="utf-8")


def approval(repository: str, revision: int = 1) -> dict[str, Any]:
    return {
        "approved_by": "operator",
        "approved_at": TIMESTAMP,
        "revision": revision,
        "policy": {
            "repository": repository,
            "commit": SHA_A,
            "path": ".atelier/policy.yaml",
        },
        "authority_ceiling": list(AUTHORITY),
        "acceptance": {"mode": "operator", "required_evidence": list(EVIDENCE)},
    }


def candidate(repository: str, number: int) -> dict[str, Any]:
    return {
        "repository": repository,
        "remote": "origin",
        "remote_url": f"git@github.com:{repository.removeprefix('github:')}.git",
        "remote_ref": f"refs/heads/scott/work-{number}",
        "base_revision": SHA_A,
        "head_revision": SHA_B,
        "pull_request": (
            f"https://github.com/{repository.removeprefix('github:')}/pull/{number}"
        ),
        "workspace_id": None,
        "published_at": TIMESTAMP,
    }


def claim(repository: str, number: int, *, with_candidate: bool) -> dict[str, Any]:
    return {
        "id": identifier("clm", number),
        "worker_run_id": identifier("run", number),
        "work_revision": 1,
        "approved_commit": SHA_A,
        "policy_commit": SHA_A,
        "ticket_observation_digest": DIGEST,
        "claimed_at": TIMESTAMP,
        "host": "codex",
        "checkpoint": {
            "sequence": 0,
            "continuation_token": f"token-{number}",
            "authorizations": [],
        },
        "candidate": candidate(repository, number) if with_candidate else None,
    }


def base_work(
    work_id: str,
    project_id: str,
    ticket_number: int,
    *,
    initiative_id: str | None = None,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "atelier.work/v1",
        "id": work_id,
        "title": f"Work {ticket_number}",
        "project_id": project_id,
        "initiative_id": initiative_id,
        "status": "draft",
        "revision": 1,
        "dependencies": dependencies or [],
        "replaces": [],
        "native_ticket": {
            "provider": "github",
            "id": str(ticket_number),
            "url": f"https://github.com/example/project-{ticket_number}/issues/{ticket_number}",
        },
        "approval": None,
        "claim": None,
        "blocking_message_id": None,
        "attempt_receipt_id": None,
        "delivery_receipt_id": None,
        "acceptance": None,
    }


def receipt(
    work: dict[str, Any],
    repository: str,
    number: int,
    *,
    outcome: str,
    with_candidate: bool,
) -> dict[str, Any]:
    current_claim = claim(repository, number, with_candidate=with_candidate)
    return {
        "schema": "atelier.receipt/v1",
        "id": identifier("rcp", number),
        "work_id": work["id"],
        "outcome": outcome,
        "approved_revision": 1,
        "approved_commit": SHA_A,
        "policy_commit": SHA_A,
        "claim_id": current_claim["id"],
        "worker_run_id": current_claim["worker_run_id"],
        "candidate": current_claim["candidate"],
        "handoff": "transferable" if with_candidate else "none",
        "native_ticket": {
            "provider": "github",
            "id": work["native_ticket"]["id"],
        },
        "validation": (
            [
                {
                    "command": "just test",
                    "outcome": "passed",
                    "candidate_revision": SHA_B,
                    "observed_at": TIMESTAMP,
                }
            ]
            if with_candidate
            else []
        ),
        "reviews": (
            [
                {
                    "mechanism": "review-code-change",
                    "verdict": "clean",
                    "candidate_revision": SHA_B,
                    "comparison_base_revision": SHA_A,
                    "observed_at": TIMESTAMP,
                }
            ]
            if with_candidate
            else []
        ),
        "unresolved_obligations": [],
        "mutation_ownership": "retained",
        "ended_at": TIMESTAMP,
    }


class MailboxFixture:
    def __init__(self, root: Path):
        self.root = root
        self.projects: dict[str, dict[str, Any]] = {}
        self.works: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, dict[str, dict[str, Any]]] = {}
        self.receipts: dict[str, dict[str, dict[str, Any]]] = {}
        write_yaml(
            root / "atelier.yaml",
            {
                "schema": "atelier.mailbox/v1",
                "realm_id": "personal",
                "canonical_branch": "main",
            },
        )

    def add_project(self, number: int) -> tuple[str, str]:
        project_id = identifier("prj", number)
        repository = f"github:example/project-{number}"
        project = {
            "schema": "atelier.project/v1",
            "id": project_id,
            "name": f"Project {number}",
            "repository": repository,
            "policy": {
                "repository": repository,
                "path": ".atelier/policy.yaml",
            },
            "native_ticket": {
                "provider": "github",
                "required_before_claim": True,
            },
            "status": "active",
        }
        self.projects[project_id] = project
        self.write_project(project_id)
        return project_id, repository

    def write_project(self, project_id: str) -> None:
        write_markdown(
            self.root / "projects" / project_id / "project.md",
            self.projects[project_id],
        )

    def add_work(
        self,
        number: int,
        status: str,
        *,
        dependencies: list[str] | None = None,
        initiative_id: str | None = None,
    ) -> str:
        project_id, repository = self.add_project(number)
        work_id = identifier("wrk", number)
        work = base_work(
            work_id,
            project_id,
            number,
            dependencies=dependencies,
            initiative_id=initiative_id,
        )
        work["status"] = status
        if status != "draft":
            work["approval"] = approval(repository)
        if status in {"active", "blocked", "delivered"}:
            work["claim"] = claim(
                repository, number, with_candidate=status == "delivered"
            )
        self.messages[work_id] = {}
        self.receipts[work_id] = {}
        if status == "blocked":
            message_id = identifier("msg", number)
            receipt_value = receipt(
                work, repository, number, outcome="blocked", with_candidate=False
            )
            work["blocking_message_id"] = message_id
            work["attempt_receipt_id"] = receipt_value["id"]
            self.messages[work_id][message_id] = {
                "schema": "atelier.message/v1",
                "id": message_id,
                "work_id": work_id,
                "kind": "needs-decision",
                "author_role": "worker",
                "worker_run_id": identifier("run", number),
                "audience": "planner",
                "in_reply_to": None,
                "resolves": None,
                "blocks": "worker",
                "created_at": TIMESTAMP,
                "subject": "Choose the bounded behavior",
            }
            self.receipts[work_id][receipt_value["id"]] = receipt_value
        if status in {"delivered", "accepted"}:
            receipt_value = receipt(
                work, repository, number, outcome="delivered", with_candidate=True
            )
            work["attempt_receipt_id"] = receipt_value["id"]
            work["delivery_receipt_id"] = receipt_value["id"]
            self.receipts[work_id][receipt_value["id"]] = receipt_value
        if status == "accepted":
            work["claim"] = None
            work["acceptance"] = {
                "receipt_id": work["delivery_receipt_id"],
                "accepted_by": "operator",
                "accepted_at": TIMESTAMP,
                "policy_commit": SHA_A,
                "candidate_revision": SHA_B,
                "evidence": {name: "satisfied" for name in EVIDENCE},
            }
        self.works[work_id] = work
        self.write_work(work_id)
        return work_id

    def write_work(self, work_id: str) -> None:
        write_markdown(
            self.root / "work" / work_id / "work.md",
            self.works[work_id],
        )
        for message_id, value in self.messages[work_id].items():
            write_markdown(
                self.root / "work" / work_id / "messages" / f"{message_id}.md",
                value,
            )
        for receipt_id, value in self.receipts[work_id].items():
            write_markdown(
                self.root / "work" / work_id / "receipts" / f"{receipt_id}.md",
                value,
            )


class MailboxContract(unittest.TestCase):
    """Define the production boundary implemented by issue 775."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "mailbox"
        self.root.mkdir()
        self.fixture = MailboxFixture(self.root)

    def assert_invalid(self, code: str) -> None:
        with self.assertRaises(MAILBOX.MailboxValidationError) as caught:
            MAILBOX.reconstruct_mailbox(self.root)
        self.assertIn(code, [item.code for item in caught.exception.diagnostics])

    def test_frozen_bundle_contains_every_v1_document_and_embedded_record(self) -> None:
        schema = json.loads(MAILBOX_SCHEMA.read_text(encoding="utf-8"))
        for name in (
            "mailbox",
            "project",
            "initiative",
            "work",
            "claim",
            "message",
            "receipt",
            "acceptance",
            "project_policy",
        ):
            self.assertIn(name, schema["$defs"])
        self.assertFalse(schema["$defs"]["work"]["additionalProperties"])

    def test_project_policy_is_strict_and_read_only(self) -> None:
        project_id, repository = self.fixture.add_project(1)
        policy = {
            "schema": "atelier.project-policy/v1",
            "mailbox": {
                "remote": "git@github.com:example/mailbox.git",
                "realm_id": "personal",
                "canonical_branch": "main",
                "project_id": project_id,
            },
            "repository": {
                "identity": repository,
                "canonical_ref": "refs/heads/main",
            },
            "ticket": {
                "provider": "github",
                "allowed_states": ["open"],
                "require_no_blockers": True,
                "material_fields": ["body", "state", "relationships"],
            },
            "execution": {
                "capability": "agent-scripts.implement-ticket/delegated-execution/v1",
                "delivery_outcome": "ready_pr",
                "parallel_assignments": False,
            },
            "authority": {"allow": list(AUTHORITY)},
            "validation": {"required_commands": ["just test", "just lint"]},
            "acceptance": {"actor": "operator", "evidence": list(EVIDENCE)},
        }
        path = Path(self.temporary.name) / "policy.yaml"
        write_yaml(path, policy)
        before = path.read_bytes()
        self.assertEqual(MAILBOX.validate_project_policy(path), policy)
        self.assertEqual(path.read_bytes(), before)
        policy["authority"]["allow"].append("merge")
        write_yaml(path, policy)
        with self.assertRaisesRegex(
            MAILBOX.MailboxValidationError, "unsupported value"
        ):
            MAILBOX.validate_project_policy(path)
        policy["authority"]["allow"] = list(AUTHORITY)
        policy["execution"]["parallel_assignments"] = 0
        write_yaml(path, policy)
        with self.assertRaisesRegex(MAILBOX.MailboxValidationError, "expected False"):
            MAILBOX.validate_project_policy(path)

    def test_fresh_clones_reconstruct_all_views_identically(self) -> None:
        initiative_id = identifier("ini", 1)
        write_markdown(
            self.root / "initiatives" / initiative_id / "initiative.md",
            {
                "schema": "atelier.initiative/v1",
                "id": initiative_id,
                "title": "One accountable outcome",
            },
        )
        accepted = self.fixture.add_work(1, "accepted", initiative_id=initiative_id)
        ready = self.fixture.add_work(
            2,
            "approved",
            dependencies=[accepted],
            initiative_id=initiative_id,
        )
        active = self.fixture.add_work(3, "active")
        blocked = self.fixture.add_work(4, "blocked")
        delivered = self.fixture.add_work(5, "delivered")
        readiness = {
            ready: {"policy": True, "ticket": True, "capability": True}
        }
        git_run(self.root, "init", "-b", "main")
        git_run(self.root, "config", "user.name", "Atelier Contract")
        git_run(self.root, "config", "user.email", "atelier@example.invalid")
        git_run(self.root, "add", ".")
        git_run(self.root, "commit", "-m", "test: freeze mailbox fixture")
        remote = Path(self.temporary.name) / "mailbox.git"
        git_run(None, "clone", "--bare", str(self.root), str(remote))
        first_clone = Path(self.temporary.name) / "fresh-clone-one"
        second_clone = Path(self.temporary.name) / "fresh-clone-two"
        git_run(None, "clone", str(remote), str(first_clone))
        git_run(None, "clone", str(remote), str(second_clone))
        first = MAILBOX.reconstruct_mailbox(first_clone, readiness=readiness)
        second = MAILBOX.reconstruct_mailbox(second_clone, readiness=readiness)
        self.assertEqual(first, second)
        self.assertEqual(first["views"]["ready"], [ready])
        self.assertEqual(first["views"]["active"], [active, blocked])
        self.assertEqual(first["views"]["blocked"], [blocked])
        self.assertEqual(first["views"]["decision_needed"], [blocked])
        self.assertEqual(first["views"]["delivered"], [delivered])
        self.assertEqual(first["views"]["accepted"], [accepted])
        self.assertEqual(first["diagnostics"], [])

    def test_ready_work_fails_closed_without_each_external_gate(self) -> None:
        ready = self.fixture.add_work(1, "approved")
        snapshot = MAILBOX.reconstruct_mailbox(self.root)
        self.assertEqual(snapshot["views"]["ready"], [])
        self.assertEqual(
            [item["code"] for item in snapshot["diagnostics"]],
            [
                "readiness-policy-unknown",
                "readiness-ticket-unknown",
                "readiness-capability-unknown",
            ],
        )
        snapshot = MAILBOX.reconstruct_mailbox(
            self.root,
            readiness={ready: {"policy": True, "ticket": False, "capability": True}},
        )
        self.assertEqual(snapshot["views"]["ready"], [])
        self.assertEqual(snapshot["diagnostics"][0]["code"], "readiness-ticket-failed")
        self.fixture.works[ready]["native_ticket"] = None
        self.fixture.write_work(ready)
        snapshot = MAILBOX.reconstruct_mailbox(
            self.root,
            readiness={ready: {"policy": True, "ticket": True, "capability": True}},
        )
        self.assertEqual(snapshot["views"]["ready"], [])
        self.assertEqual(snapshot["diagnostics"][0]["code"], "readiness-ticket-missing")

    def test_unsupported_schema_and_unknown_field_fail_closed(self) -> None:
        manifest = self.root / "atelier.yaml"
        value = {
            "schema": "atelier.mailbox/v2",
            "realm_id": "personal",
            "canonical_branch": "main",
        }
        write_yaml(manifest, value)
        self.assert_invalid("unsupported-schema")
        value["schema"] = "atelier.mailbox/v1"
        value["projection"] = "cache.db"
        write_yaml(manifest, value)
        self.assert_invalid("schema-unknown")

    def test_path_and_identifier_must_agree(self) -> None:
        work_id = self.fixture.add_work(1, "draft")
        self.fixture.works[work_id]["id"] = identifier("wrk", 99)
        self.fixture.write_work(work_id)
        self.assert_invalid("path-identity")

    def test_lifecycle_combinations_are_not_inferred(self) -> None:
        work_id = self.fixture.add_work(1, "approved")
        self.fixture.works[work_id]["status"] = "accepted"
        self.fixture.write_work(work_id)
        self.assert_invalid("lifecycle")

    def test_missing_and_cyclic_dependencies_fail_closed(self) -> None:
        first = self.fixture.add_work(1, "approved")
        self.fixture.works[first]["dependencies"] = [identifier("wrk", 99)]
        self.fixture.write_work(first)
        self.assert_invalid("dependencies-reference")
        second = self.fixture.add_work(2, "approved")
        self.fixture.works[first]["dependencies"] = [second]
        self.fixture.works[second]["dependencies"] = [first]
        self.fixture.write_work(first)
        self.fixture.write_work(second)
        self.assert_invalid("dependency-cycle")

    def test_resolved_message_cannot_remain_the_current_blocker(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        blocker_id = self.fixture.works[work_id]["blocking_message_id"]
        resolving_id = identifier("msg", 2)
        resolving = copy.deepcopy(self.fixture.messages[work_id][blocker_id])
        resolving.update(
            {
                "id": resolving_id,
                "kind": "instruction",
                "author_role": "planner",
                "worker_run_id": None,
                "audience": "worker",
                "in_reply_to": blocker_id,
                "resolves": blocker_id,
                "blocks": None,
                "subject": "Use the bounded behavior",
            }
        )
        self.fixture.messages[work_id][resolving_id] = resolving
        self.fixture.write_work(work_id)
        self.assert_invalid("blocking-message")

    def test_message_authorship_and_candidate_observations_are_bound(self) -> None:
        blocked = self.fixture.add_work(1, "blocked")
        blocker_id = self.fixture.works[blocked]["blocking_message_id"]
        self.fixture.messages[blocked][blocker_id]["worker_run_id"] = None
        self.fixture.write_work(blocked)
        self.assert_invalid("message-author")

        shutil.rmtree(self.root)
        self.root.mkdir()
        self.fixture = MailboxFixture(self.root)
        delivered = self.fixture.add_work(2, "delivered")
        receipt_id = self.fixture.works[delivered]["delivery_receipt_id"]
        self.fixture.receipts[delivered][receipt_id]["validation"][0][
            "candidate_revision"
        ] = "d" * 40
        self.fixture.write_work(delivered)
        self.assert_invalid("validation-candidate")

    def test_checkpoint_ledger_must_match_its_tail(self) -> None:
        work_id = self.fixture.add_work(1, "active")
        self.fixture.works[work_id]["claim"]["checkpoint"]["sequence"] = 1
        self.fixture.write_work(work_id)
        self.assert_invalid("checkpoint-sequence")

    def test_delivery_and_acceptance_bind_exact_receipt_candidate(self) -> None:
        work_id = self.fixture.add_work(1, "accepted")
        self.fixture.works[work_id]["acceptance"]["candidate_revision"] = "d" * 40
        self.fixture.write_work(work_id)
        self.assert_invalid("acceptance-identity")

    def test_parallel_active_assignments_for_one_project_fail_closed(self) -> None:
        first = self.fixture.add_work(1, "active")
        second = self.fixture.add_work(2, "active")
        self.fixture.works[second]["project_id"] = self.fixture.works[first]["project_id"]
        self.fixture.write_work(second)
        self.assert_invalid("parallel-assignments")

    def test_duplicate_yaml_keys_and_unexpected_layout_fail_closed(self) -> None:
        manifest = self.root / "atelier.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + 'realm_id: "other"\n',
            encoding="utf-8",
        )
        self.assert_invalid("yaml-duplicate-key")
        write_yaml(
            manifest,
            {
                "schema": "atelier.mailbox/v1",
                "realm_id": "personal",
                "canonical_branch": "main",
            },
        )
        project_id, _ = self.fixture.add_project(1)
        (self.root / "projects" / project_id / "cache.json").write_text("{}\n")
        self.assert_invalid("layout")

    def test_symbolic_links_cannot_supply_normative_documents(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "projects").mkdir()
        (self.root / "projects" / identifier("prj", 1)).symlink_to(
            outside, target_is_directory=True
        )
        self.assert_invalid("symlink")

    def test_readiness_input_rejects_unknown_work_and_gates(self) -> None:
        ready = self.fixture.add_work(1, "approved")
        with self.assertRaisesRegex(MAILBOX.MailboxValidationError, "unknown work"):
            MAILBOX.reconstruct_mailbox(
                self.root,
                readiness={identifier("wrk", 99): {"policy": True}},
            )
        with self.assertRaisesRegex(MAILBOX.MailboxValidationError, "only policy"):
            MAILBOX.reconstruct_mailbox(
                self.root,
                readiness={ready: {"database": True}},
            )


if __name__ == "__main__":
    unittest.main()

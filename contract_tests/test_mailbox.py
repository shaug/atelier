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
    worker_run_id = identifier("run", number)
    authorizations = (
        [
            {
                "sequence": 1,
                "invocation_id": worker_run_id,
                "phase": "pre_external_mutation",
                "action": "repository.candidate.push",
                "proposed_effect_digest": DIGEST,
                "candidate_head": None,
                "acknowledged_candidate_head": None,
                "recorded_at": TIMESTAMP,
            },
            {
                "sequence": 2,
                "invocation_id": worker_run_id,
                "phase": "candidate_published",
                "action": "repository.candidate.push",
                "proposed_effect_digest": DIGEST,
                "candidate_head": SHA_B,
                "acknowledged_candidate_head": SHA_B,
                "recorded_at": TIMESTAMP,
            },
        ]
        if with_candidate
        else []
    )
    return {
        "id": identifier("clm", number),
        "worker_run_id": worker_run_id,
        "work_revision": 1,
        "approved_commit": SHA_A,
        "policy_commit": SHA_A,
        "ticket_observation_digest": DIGEST,
        "claimed_at": TIMESTAMP,
        "host": "codex",
        "checkpoint": {
            "sequence": len(authorizations),
            "continuation_token": f"token-{number}",
            "authorizations": authorizations,
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
        policy["execution"]["parallel_assignments"] = False
        policy["repository"]["canonical_ref"] = "refs/heads/main..malformed"
        write_yaml(path, policy)
        with self.assertRaisesRegex(MAILBOX.MailboxValidationError, "git-ref"):
            MAILBOX.validate_project_policy(path)
        policy["repository"]["canonical_ref"] = "refs/heads/main"
        policy["mailbox"]["canonical_branch"] = "main..malformed"
        write_yaml(path, policy)
        before = path.read_bytes()
        with self.assertRaisesRegex(MAILBOX.MailboxValidationError, "git-ref"):
            MAILBOX.validate_project_policy(path)
        self.assertEqual(path.read_bytes(), before)
        policy["mailbox"]["canonical_branch"] = "main"
        policy["mailbox"]["remote"] = "https://user:secret@github.com/example/mailbox.git"
        write_yaml(path, policy)
        before = path.read_bytes()
        with self.assertRaisesRegex(
            MAILBOX.MailboxValidationError, "remote-credentials"
        ):
            MAILBOX.validate_project_policy(path)
        self.assertEqual(path.read_bytes(), before)

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

    def test_fresh_clones_report_identical_relative_diagnostics(self) -> None:
        manifest = self.root / "atelier.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + 'realm_id: "other"\n',
            encoding="utf-8",
        )
        git_run(self.root, "init", "-b", "main")
        git_run(self.root, "config", "user.name", "Atelier Contract")
        git_run(self.root, "config", "user.email", "atelier@example.invalid")
        git_run(self.root, "add", ".")
        git_run(self.root, "commit", "-m", "test: freeze malformed mailbox fixture")
        remote = Path(self.temporary.name) / "malformed-mailbox.git"
        git_run(None, "clone", "--bare", str(self.root), str(remote))
        first_clone = Path(self.temporary.name) / "malformed-clone-one"
        second_clone = Path(self.temporary.name) / "malformed-clone-two"
        git_run(None, "clone", str(remote), str(first_clone))
        git_run(None, "clone", str(remote), str(second_clone))

        def diagnostics(clone: Path) -> list[dict[str, str]]:
            with self.assertRaises(MAILBOX.MailboxValidationError) as caught:
                MAILBOX.reconstruct_mailbox(clone)
            return [item.as_dict() for item in caught.exception.diagnostics]

        first = diagnostics(first_clone)
        second = diagnostics(second_clone)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["path"], "atelier.yaml")

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

    def test_unresolved_worker_blocker_requires_the_canonical_pointer(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        work["status"] = "active"
        work["blocking_message_id"] = None
        self.fixture.write_work(work_id)

        self.assert_invalid("blocking-message")

    def test_blocked_work_has_exactly_one_unresolved_worker_blocker(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        blocker_id = self.fixture.works[work_id]["blocking_message_id"]
        second_id = identifier("msg", 2)
        second = copy.deepcopy(self.fixture.messages[work_id][blocker_id])
        second["id"] = second_id
        self.fixture.messages[work_id][second_id] = second
        self.fixture.write_work(work_id)

        self.assert_invalid("blocking-message")

    def test_nonblocking_decision_can_be_resolved(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        decision_id = work["blocking_message_id"]
        decision = self.fixture.messages[work_id][decision_id]
        work["status"] = "active"
        work["blocking_message_id"] = None
        decision["blocks"] = None
        self.fixture.write_work(work_id)
        unresolved = MAILBOX.reconstruct_mailbox(self.root)
        self.assertEqual(unresolved["views"]["decision_needed"], [work_id])

        resolution_id = identifier("msg", 2)
        resolution = copy.deepcopy(decision)
        resolution.update(
            {
                "id": resolution_id,
                "kind": "instruction",
                "author_role": "planner",
                "worker_run_id": None,
                "in_reply_to": decision_id,
                "resolves": decision_id,
                "subject": "Decision supplied",
            }
        )
        self.fixture.messages[work_id][resolution_id] = resolution
        self.fixture.write_work(work_id)

        resolved = MAILBOX.reconstruct_mailbox(self.root)

        self.assertEqual(resolved["views"]["decision_needed"], [])
        self.assertEqual(resolved["views"]["active"], [work_id])

    def test_current_blocker_belongs_to_the_claiming_worker(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        blocker_id = work["blocking_message_id"]
        self.fixture.messages[work_id][blocker_id]["worker_run_id"] = identifier("run", 99)
        self.fixture.write_work(work_id)

        self.assert_invalid("blocker-actor")

    def test_worker_cannot_resolve_its_own_decision(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        blocker_id = work["blocking_message_id"]
        blocker = self.fixture.messages[work_id][blocker_id]
        resolution_id = identifier("msg", 2)
        resolution = copy.deepcopy(blocker)
        resolution.update(
            {
                "id": resolution_id,
                "kind": "instruction",
                "in_reply_to": blocker_id,
                "resolves": blocker_id,
                "blocks": None,
                "subject": "Worker self-resolution",
            }
        )
        self.fixture.messages[work_id][resolution_id] = resolution
        work["status"] = "active"
        work["blocking_message_id"] = None
        self.fixture.write_work(work_id)

        self.assert_invalid("resolution-actor")

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

    def test_current_candidate_requires_publication_acknowledgement(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        checkpoint = self.fixture.works[work_id]["claim"]["checkpoint"]
        checkpoint["sequence"] = 0
        checkpoint["authorizations"] = []
        self.fixture.write_work(work_id)
        self.assert_invalid("candidate-acknowledgement")

    def test_append_only_candidate_publication_history_reconstructs(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        next_head = "d" * 40
        checkpoint = work["claim"]["checkpoint"]
        checkpoint["sequence"] = 4
        checkpoint["continuation_token"] = "token-1-next"
        checkpoint["authorizations"].extend(
            [
                {
                    "sequence": 3,
                    "invocation_id": work["claim"]["worker_run_id"],
                    "phase": "pre_external_mutation",
                    "action": "repository.candidate.push",
                    "proposed_effect_digest": DIGEST,
                    "candidate_head": SHA_B,
                    "acknowledged_candidate_head": None,
                    "recorded_at": TIMESTAMP,
                },
                {
                    "sequence": 4,
                    "invocation_id": work["claim"]["worker_run_id"],
                    "phase": "candidate_published",
                    "action": "repository.candidate.push",
                    "proposed_effect_digest": DIGEST,
                    "candidate_head": next_head,
                    "acknowledged_candidate_head": next_head,
                    "recorded_at": TIMESTAMP,
                },
            ]
        )
        work["claim"]["candidate"]["head_revision"] = next_head
        receipt_id = work["delivery_receipt_id"]
        receipt_document = self.fixture.receipts[work_id][receipt_id]
        receipt_document["candidate"]["head_revision"] = next_head
        receipt_document["validation"][0]["candidate_revision"] = next_head
        receipt_document["reviews"][0]["candidate_revision"] = next_head
        self.fixture.write_work(work_id)

        snapshot = MAILBOX.reconstruct_mailbox(self.root)

        self.assertEqual(snapshot["views"]["delivered"], [work_id])

    def test_transferable_candidate_can_be_adopted_by_a_fresh_claim(self) -> None:
        work_id = self.fixture.add_work(1, "active")
        work = self.fixture.works[work_id]
        repository = self.fixture.projects[work["project_id"]]["repository"]
        prior_claim = claim(repository, 1, with_candidate=True)
        work["claim"] = prior_claim
        released = receipt(
            work,
            repository,
            1,
            outcome="released",
            with_candidate=True,
        )
        released["mutation_ownership"] = "relinquished"
        work["attempt_receipt_id"] = released["id"]
        self.fixture.receipts[work_id][released["id"]] = released
        adopted_claim = claim(repository, 2, with_candidate=False)
        adopted_claim["candidate"] = copy.deepcopy(prior_claim["candidate"])
        work["claim"] = adopted_claim
        self.fixture.write_work(work_id)

        snapshot = MAILBOX.reconstruct_mailbox(self.root)

        self.assertEqual(snapshot["views"]["active"], [work_id])

        work["claim"]["candidate"] = None
        self.fixture.write_work(work_id)
        self.assert_invalid("candidate-acknowledgement")

    def test_git_refs_and_github_reference_identities_fail_closed(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        work["claim"]["candidate"]["remote_ref"] = "refs/heads/main..malformed"
        self.fixture.write_work(work_id)
        self.assert_invalid("git-ref")

        shutil.rmtree(self.root)
        self.root.mkdir()
        self.fixture = MailboxFixture(self.root)
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        work["native_ticket"]["url"] = "https://github.com/example/project-1/issues/999"
        self.fixture.write_work(work_id)
        self.assert_invalid("ticket-url")

        work["native_ticket"]["url"] = "https://github.com/example/project-1/issues/1"
        receipt_id = work["delivery_receipt_id"]
        mismatched_url = "https://github.com/another/project/pull/1"
        work["claim"]["candidate"]["pull_request"] = mismatched_url
        self.fixture.receipts[work_id][receipt_id]["candidate"]["pull_request"] = mismatched_url
        self.fixture.write_work(work_id)
        self.assert_invalid("candidate-pull-request")

    def test_approved_work_retains_only_a_released_attempt(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        work["status"] = "approved"
        work["claim"] = None
        work["blocking_message_id"] = None
        self.fixture.write_work(work_id)

        self.assert_invalid("attempt-outcome")

    def test_historical_receipts_survive_project_and_ticket_revision(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        old_repository = self.fixture.projects[work["project_id"]]["repository"]
        released = receipt(
            work,
            old_repository,
            2,
            outcome="released",
            with_candidate=True,
        )
        released["mutation_ownership"] = "relinquished"
        self.fixture.receipts[work_id][released["id"]] = released

        next_project_id, _ = self.fixture.add_project(2)
        work["project_id"] = next_project_id
        work["revision"] = 2
        work["status"] = "draft"
        work["native_ticket"] = {
            "provider": "github",
            "id": "2",
            "url": "https://github.com/example/project-2/issues/2",
        }
        work["approval"] = None
        work["claim"] = None
        work["attempt_receipt_id"] = None
        work["delivery_receipt_id"] = None
        self.fixture.write_work(work_id)

        snapshot = MAILBOX.reconstruct_mailbox(self.root)

        self.assertEqual(snapshot["work"][0]["status"], "draft")
        self.assertEqual(snapshot["work"][0]["project_id"], next_project_id)
        self.assertEqual(len(self.fixture.receipts[work_id]), 2)

    def test_blocked_work_requires_a_blocked_retained_attempt(self) -> None:
        work_id = self.fixture.add_work(1, "blocked")
        work = self.fixture.works[work_id]
        receipt_id = work["attempt_receipt_id"]
        attempt = self.fixture.receipts[work_id][receipt_id]
        attempt["outcome"] = "released"
        attempt["mutation_ownership"] = "relinquished"
        self.fixture.write_work(work_id)

        self.assert_invalid("attempt-outcome")

    def test_generated_identifiers_are_global_across_work_threads(self) -> None:
        first = self.fixture.add_work(1, "delivered")
        second = self.fixture.add_work(2, "delivered")
        first_work = self.fixture.works[first]
        second_work = self.fixture.works[second]
        first_receipt_id = first_work["delivery_receipt_id"]
        second_receipt_id = second_work["delivery_receipt_id"]
        second_receipt = self.fixture.receipts[second].pop(second_receipt_id)
        second_receipt["id"] = first_receipt_id
        second_receipt["claim_id"] = first_work["claim"]["id"]
        second_receipt["worker_run_id"] = first_work["claim"]["worker_run_id"]
        self.fixture.receipts[second][first_receipt_id] = second_receipt
        second_work["claim"]["id"] = first_work["claim"]["id"]
        second_work["claim"]["worker_run_id"] = first_work["claim"]["worker_run_id"]
        for entry in second_work["claim"]["checkpoint"]["authorizations"]:
            entry["invocation_id"] = first_work["claim"]["worker_run_id"]
        second_work["attempt_receipt_id"] = first_receipt_id
        second_work["delivery_receipt_id"] = first_receipt_id
        self.fixture.write_work(second)

        self.assert_invalid("identity-collision")

    def test_historical_receipt_execution_identities_stay_in_one_work(self) -> None:
        first = self.fixture.add_work(1, "accepted")
        second = self.fixture.add_work(2, "accepted")
        first_receipt_id = self.fixture.works[first]["delivery_receipt_id"]
        second_receipt_id = self.fixture.works[second]["delivery_receipt_id"]
        first_receipt = self.fixture.receipts[first][first_receipt_id]
        second_receipt = self.fixture.receipts[second][second_receipt_id]
        second_receipt["claim_id"] = first_receipt["claim_id"]
        second_receipt["worker_run_id"] = first_receipt["worker_run_id"]
        self.fixture.write_work(second)

        self.assert_invalid("identity-collision")

    def test_historical_execution_identity_pairing_is_bijective(self) -> None:
        work_id = self.fixture.add_work(1, "accepted")
        delivery_id = self.fixture.works[work_id]["delivery_receipt_id"]
        delivery = self.fixture.receipts[work_id][delivery_id]
        released = copy.deepcopy(delivery)
        released["id"] = identifier("rcp", 2)
        released["outcome"] = "released"
        released["worker_run_id"] = identifier("run", 2)
        released["mutation_ownership"] = "relinquished"
        self.fixture.receipts[work_id][released["id"]] = released
        self.fixture.write_work(work_id)

        self.assert_invalid("identity-collision")

    def test_worker_message_run_identity_stays_in_one_work(self) -> None:
        first = self.fixture.add_work(1, "accepted")
        second = self.fixture.add_work(2, "blocked")
        first_receipt_id = self.fixture.works[first]["delivery_receipt_id"]
        first_run_id = self.fixture.receipts[first][first_receipt_id]["worker_run_id"]
        blocker_id = self.fixture.works[second]["blocking_message_id"]
        self.fixture.messages[second][blocker_id]["worker_run_id"] = first_run_id
        self.fixture.write_work(second)

        self.assert_invalid("identity-collision")

    def test_mailbox_canonical_branch_must_be_a_git_branch_name(self) -> None:
        manifest = self.root / "atelier.yaml"
        for branch in ("main..malformed", "-hidden"):
            with self.subTest(branch=branch):
                write_yaml(
                    manifest,
                    {
                        "schema": "atelier.mailbox/v1",
                        "realm_id": "personal",
                        "canonical_branch": branch,
                    },
                )
                self.assert_invalid("git-ref")

    def test_timestamps_and_candidate_remote_urls_fail_closed(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        receipt_id = work["delivery_receipt_id"]
        invalid_timestamp = "2026-07-27 12:00:00+00:00"
        work["claim"]["candidate"]["published_at"] = invalid_timestamp
        self.fixture.receipts[work_id][receipt_id]["candidate"][
            "published_at"
        ] = invalid_timestamp
        self.fixture.write_work(work_id)
        self.assert_invalid("schema-one-of")

        shutil.rmtree(self.root)
        self.root.mkdir()
        self.fixture = MailboxFixture(self.root)
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        receipt_id = work["delivery_receipt_id"]
        mismatched_remote = "git@github.com:another/project.git"
        work["claim"]["candidate"]["remote_url"] = mismatched_remote
        self.fixture.receipts[work_id][receipt_id]["candidate"][
            "remote_url"
        ] = mismatched_remote
        self.fixture.write_work(work_id)
        self.assert_invalid("candidate-remote-url")

    def test_workspace_id_is_portable_and_not_a_machine_local_path(self) -> None:
        work_id = self.fixture.add_work(1, "delivered")
        work = self.fixture.works[work_id]
        receipt_id = work["delivery_receipt_id"]
        durable_id = "codex:task-019f9a9e"
        work["claim"]["candidate"]["workspace_id"] = durable_id
        self.fixture.receipts[work_id][receipt_id]["candidate"]["workspace_id"] = durable_id
        self.fixture.write_work(work_id)
        snapshot = MAILBOX.reconstruct_mailbox(self.root)
        self.assertEqual(snapshot["views"]["delivered"], [work_id])

        for machine_path in (
            "/Users/alice/private/worktree",
            r"C:\Users\alice\private\worktree",
        ):
            with self.subTest(machine_path=machine_path):
                shutil.rmtree(self.root)
                self.root.mkdir()
                self.fixture = MailboxFixture(self.root)
                work_id = self.fixture.add_work(1, "delivered")
                work = self.fixture.works[work_id]
                receipt_id = work["delivery_receipt_id"]
                work["claim"]["candidate"]["workspace_id"] = machine_path
                self.fixture.receipts[work_id][receipt_id]["candidate"][
                    "workspace_id"
                ] = machine_path
                self.fixture.write_work(work_id)
                self.assert_invalid("schema-one-of")

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

    def test_github_repository_case_aliases_share_one_identity(self) -> None:
        self.fixture.add_work(1, "active")
        second = self.fixture.add_work(2, "active")
        second_project_id = self.fixture.works[second]["project_id"]
        repository_alias = "github:EXAMPLE/PROJECT-1"
        second_project = self.fixture.projects[second_project_id]
        second_project["repository"] = repository_alias
        second_project["policy"]["repository"] = repository_alias
        second_work = self.fixture.works[second]
        second_work["approval"]["policy"]["repository"] = repository_alias
        second_work["native_ticket"]["url"] = (
            "https://github.com/EXAMPLE/PROJECT-1/issues/2"
        )
        self.fixture.write_project(second_project_id)
        self.fixture.write_work(second)

        with self.assertRaises(MAILBOX.MailboxValidationError) as caught:
            MAILBOX.reconstruct_mailbox(self.root)
        codes = {item.code for item in caught.exception.diagnostics}
        self.assertTrue(
            {"duplicate-repository", "parallel-assignments"}.issubset(codes)
        )

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

    def test_malformed_single_quoted_yaml_fails_closed(self) -> None:
        project_id, _ = self.fixture.add_project(1)
        project_path = self.root / "projects" / project_id / "project.md"
        project_path.write_text(
            project_path.read_text(encoding="utf-8").replace(
                'name: "Project 1"',
                "name: 'foo'bar'",
            ),
            encoding="utf-8",
        )
        self.assert_invalid("yaml-string")

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

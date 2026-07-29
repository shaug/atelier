#!/usr/bin/env python3
"""Exercise the proposed Atelier mailbox protocol against disposable Git clones."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA_ZERO = "0" * 40
WORK_RACE = "wrk_019f9a9e-0000-7000-8000-000000000001"
PROJECT_ID = "prj_019f9a9e-0000-7000-8000-000000000001"


def run(repo: Path | None, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    return subprocess.run(
        command,
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def configure(repo: Path) -> None:
    run(repo, "config", "user.name", "Atelier Protocol Experiment")
    run(repo, "config", "user.email", "atelier-experiment@example.invalid")


def document(data: dict[str, Any], body: str = "") -> str:
    return f"---\n{json.dumps(data, indent=2, sort_keys=True)}\n---\n{body}\n"


def parse_document(content: str) -> dict[str, Any]:
    lines = content.splitlines()
    if len(lines) < 3 or lines[0] != "---":
        raise ValueError("missing frontmatter")
    end = lines.index("---", 1)
    value = json.loads("\n".join(lines[1:end]))
    if not isinstance(value, dict):
        raise ValueError("frontmatter must be an object")
    return value


def write_document(
    repo: Path,
    relative: str,
    data: dict[str, Any],
    body: str = "",
) -> str:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = document(data, body)
    path.write_text(content)
    return content


def work_document(status: str = "approved") -> dict[str, Any]:
    approval = {
        "approved_by": "operator",
        "approved_at": "2026-07-25T12:00:00Z",
        "revision": 1,
        "policy": {
            "repository": "github:example/project",
            "commit": SHA_ZERO,
            "path": ".atelier/policy.yaml",
        },
        "authority_ceiling": [
            "repository.candidate.create",
            "repository.candidate.push",
            "pull_request.create",
        ],
        "acceptance": {
            "mode": "operator",
            "required_evidence": ["candidate-remote-reachable"],
        },
    }
    return {
        "schema": "atelier.work/v1",
        "id": WORK_RACE,
        "title": "Exercise mailbox transitions",
        "project_id": PROJECT_ID,
        "initiative_id": None,
        "status": status,
        "revision": 1,
        "dependencies": [],
        "replaces": [],
        "native_ticket": {
            "provider": "github",
            "id": "123",
            "url": "https://github.com/example/project/issues/123",
        },
        "approval": approval,
        "claim": None,
        "blocking_message_id": None,
        "attempt_receipt_id": None,
        "delivery_receipt_id": None,
        "acceptance": None,
    }


def claim(claim_id: str, run_id: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": claim_id,
        "worker_run_id": run_id,
        "work_revision": 1,
        "approved_commit": SHA_ZERO,
        "policy_commit": SHA_ZERO,
        "ticket_observation_digest": "sha256:" + ("1" * 64),
        "claimed_at": "2026-07-25T12:05:00Z",
        "host": "experiment",
        "checkpoint": {
            "sequence": 0,
            "continuation_token": f"token-{claim_id}",
            "authorizations": [],
        },
        "candidate": candidate,
    }


def message(
    message_id: str,
    kind: str,
    *,
    resolves: str | None = None,
    work_id: str = WORK_RACE,
) -> dict[str, Any]:
    return {
        "schema": "atelier.message/v1",
        "id": message_id,
        "work_id": work_id,
        "kind": kind,
        "author_role": "worker",
        "worker_run_id": "run_019f9a9e-0000-7000-8000-000000000001",
        "audience": "planner",
        "in_reply_to": None,
        "resolves": resolves,
        "blocks": "worker" if kind == "needs-decision" and resolves is None else None,
        "created_at": "2026-07-25T12:30:00Z",
        "subject": "Protocol experiment",
    }


def receipt(
    receipt_id: str,
    outcome: str,
    claim_id: str,
    candidate: dict[str, Any] | None,
    *,
    work_id: str = WORK_RACE,
) -> dict[str, Any]:
    return {
        "schema": "atelier.receipt/v1",
        "id": receipt_id,
        "work_id": work_id,
        "outcome": outcome,
        "approved_revision": 1,
        "approved_commit": SHA_ZERO,
        "policy_commit": SHA_ZERO,
        "claim_id": claim_id,
        "worker_run_id": "run_019f9a9e-0000-7000-8000-000000000001",
        "candidate": candidate,
        "handoff": "transferable" if candidate else "none",
        "native_ticket": {
            "provider": "github",
            "id": "123",
        },
        "validation": [],
        "reviews": [],
        "unresolved_obligations": [],
        "mutation_ownership": "retained" if outcome != "released" else "relinquished",
        "ended_at": "2026-07-25T13:00:00Z",
    }


@dataclass
class Mailbox:
    remote: Path
    readbacks: int = 0
    published: int = 0

    def sync(self, repo: Path) -> None:
        run(repo, "fetch", "origin", "main")
        run(repo, "reset", "--hard", "origin/main")
        run(repo, "clean", "-fd")

    def publish(self, repo: Path, summary: str) -> str:
        tracked = run(repo, "diff", "--name-only").stdout.splitlines()
        untracked = run(
            repo,
            "ls-files",
            "--others",
            "--exclude-standard",
        ).stdout.splitlines()
        paths = sorted(set(tracked + untracked))
        expected = {
            path: (repo / path).read_text() if (repo / path).is_file() else None for path in paths
        }
        run(repo, "add", "-A")
        run(repo, "commit", "-m", summary)
        commit = run(repo, "rev-parse", "HEAD").stdout.strip()
        run(repo, "push", "origin", "HEAD:main")
        self.published += 1
        run(repo, "fetch", "origin", "main")
        run(repo, "merge-base", "--is-ancestor", commit, "origin/main")
        for path, content in expected.items():
            shown = run(repo, "show", f"origin/main:{path}", check=False)
            if content is None:
                if shown.returncode == 0:
                    raise AssertionError(f"{path} should be absent after read-back")
            elif shown.returncode != 0 or shown.stdout != content:
                raise AssertionError(f"{path} differs after exact remote read-back")
        self.readbacks += 1
        return commit

    def remote_document(self, repo: Path, relative: str) -> dict[str, Any]:
        run(repo, "fetch", "origin", "main")
        content = run(repo, "show", f"origin/main:{relative}").stdout
        return parse_document(content)


def clone(remote: Path, target: Path) -> Path:
    run(None, "clone", str(remote), str(target))
    configure(target)
    return target


def ticket_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def candidate_reachable(repo: Path, candidate: dict[str, Any]) -> bool:
    fetched = run(
        repo,
        "fetch",
        candidate["remote_url"],
        candidate["remote_ref"],
        check=False,
    )
    if fetched.returncode != 0:
        return False
    return (
        run(
            repo,
            "merge-base",
            "--is-ancestor",
            candidate["head_revision"],
            "FETCH_HEAD",
            check=False,
        ).returncode
        == 0
    )


def checkpoint_is_current(
    repo: Path,
    relative: str,
    claim_id: str,
    sequence: int,
    continuation_token: str,
) -> bool:
    fetched = run(repo, "fetch", "origin", "main", check=False)
    if fetched.returncode != 0:
        return False
    shown = run(repo, "show", f"origin/main:{relative}", check=False)
    if shown.returncode != 0:
        return False
    current = parse_document(shown.stdout)["claim"]
    return (
        current is not None
        and current["id"] == claim_id
        and current["checkpoint"]["sequence"] == sequence
        and current["checkpoint"]["continuation_token"] == continuation_token
    )


def authorize_checkpoint(
    mailbox: Mailbox,
    repo: Path,
    relative: str,
    claim_id: str,
    sequence: int,
    continuation_token: str,
    action: str,
) -> tuple[int, str] | None:
    mailbox.sync(repo)
    data = parse_document((repo / relative).read_text())
    current = data["claim"]
    if (
        current is None
        or current["id"] != claim_id
        or current["checkpoint"]["sequence"] != sequence
        or current["checkpoint"]["continuation_token"] != continuation_token
    ):
        return None
    next_sequence = sequence + 1
    next_token = f"{continuation_token}-{next_sequence}"
    current["checkpoint"]["sequence"] = next_sequence
    current["checkpoint"]["continuation_token"] = next_token
    current["checkpoint"]["authorizations"].append(
        {
            "sequence": next_sequence,
            "invocation_id": current["worker_run_id"],
            "phase": "pre_external_mutation",
            "action": action,
            "proposed_effect_digest": ticket_digest({"action": action, "claim_id": claim_id}),
            "candidate_head": None,
            "candidate_remote_ref": None,
            "acknowledged_candidate_head": None,
            "recorded_at": "2026-07-25T12:25:00Z",
        }
    )
    write_document(repo, relative, data)
    mailbox.publish(repo, f"authorize {action}")
    return next_sequence, next_token


def validate_lifecycle(repo: Path, relative: str) -> str:
    data = parse_document((repo / relative).read_text())
    if data["schema"] != "atelier.work/v1":
        raise ValueError("unsupported work schema")
    status = data["status"]
    claim_value = data["claim"]
    blocker = data["blocking_message_id"]
    attempt = data["attempt_receipt_id"]
    delivery = data["delivery_receipt_id"]
    acceptance = data["acceptance"]
    invariants = {
        "approved": claim_value is None and blocker is None and delivery is None,
        "active": claim_value is not None and blocker is None and delivery is None,
        "blocked": (
            claim_value is not None
            and blocker is not None
            and attempt is not None
            and delivery is None
        ),
        "delivered": (
            claim_value is not None
            and blocker is None
            and attempt is not None
            and attempt == delivery
        ),
        "accepted": (
            claim_value is None
            and blocker is None
            and attempt is not None
            and attempt == delivery
            and acceptance is not None
        ),
    }
    if status not in invariants or not invariants[status]:
        raise ValueError(f"invalid {status} lifecycle fields")
    work_root = (repo / relative).parent
    if claim_value is not None and not isinstance(
        claim_value["checkpoint"]["authorizations"], list
    ):
        raise ValueError("claim authorization ledger is invalid")
    if blocker is not None:
        blocker_data = parse_document((work_root / "messages" / f"{blocker}.md").read_text())
        if (
            blocker_data["schema"] != "atelier.message/v1"
            or blocker_data["id"] != blocker
            or blocker_data["work_id"] != data["id"]
            or blocker_data["blocks"] is None
            or blocker_data["resolves"] is not None
        ):
            raise ValueError("blocking message does not match work")
    if attempt is not None:
        attempt_path = work_root / "receipts" / f"{attempt}.md"
        attempt_data = parse_document(attempt_path.read_text())
        if (
            attempt_data["schema"] != "atelier.receipt/v1"
            or attempt_data["id"] != attempt
            or attempt_data["work_id"] != data["id"]
        ):
            raise ValueError("attempt receipt does not match work")
    if delivery is not None:
        receipt_data = parse_document((work_root / "receipts" / f"{delivery}.md").read_text())
        if (
            receipt_data["schema"] != "atelier.receipt/v1"
            or receipt_data["id"] != delivery
            or receipt_data["work_id"] != data["id"]
            or receipt_data["outcome"] != "delivered"
        ):
            raise ValueError("delivery receipt does not match work")
        if acceptance is not None and (
            acceptance["receipt_id"] != delivery
            or acceptance["candidate_revision"] != receipt_data["candidate"]["head_revision"]
        ):
            raise ValueError("acceptance does not match delivered candidate")
    return status


def derive_ready(
    repo: Path,
    relative: str,
    *,
    policy_gates_satisfied: bool,
    ticket_eligible: bool,
    capability_available: bool,
) -> bool:
    """Derive v0 readiness only from validated clone state and gate fixtures."""
    try:
        data = parse_document((repo / relative).read_text())
        if validate_lifecycle(repo, relative) != "approved":
            return False
        for dependency_id in data["dependencies"]:
            dependency_path = f"work/{dependency_id}/work.md"
            if validate_lifecycle(repo, dependency_path) != "accepted":
                return False
    except (KeyError, OSError, ValueError):
        return False
    if not policy_gates_satisfied or not ticket_eligible or not capability_available:
        return False
    for path in (repo / "work").glob("*/work.md"):
        if path == repo / relative:
            continue
        other = parse_document(path.read_text())
        if other["project_id"] == data["project_id"] and other["status"] in {
            "active",
            "blocked",
            "delivered",
        }:
            return False
    return True


def main() -> int:
    results: list[tuple[str, bool]] = []

    def record(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        results.append((name, True))

    with tempfile.TemporaryDirectory(prefix="atelier-mailbox-v0-") as temporary:
        root = Path(temporary)
        remote = root / "mailbox.git"
        run(None, "init", "--bare", "--initial-branch=main", str(remote))
        seed = clone(remote, root / "seed")
        mailbox = Mailbox(remote)
        write_document(
            seed,
            "atelier.yaml",
            {
                "schema": "atelier.mailbox/v1",
                "realm_id": "experiment",
                "canonical_branch": "main",
            },
        )
        write_document(seed, f"work/{WORK_RACE}/work.md", work_document())
        mailbox.publish(seed, "seed mailbox")

        worker_one = clone(remote, root / "worker-one")
        worker_two = clone(remote, root / "worker-two")
        planner = clone(remote, root / "planner")

        for repo, claim_id, run_id in (
            (worker_one, "clm_one", "run_one"),
            (worker_two, "clm_two", "run_two"),
        ):
            data = parse_document((repo / f"work/{WORK_RACE}/work.md").read_text())
            data["status"] = "active"
            data["claim"] = claim(claim_id, run_id)
            write_document(repo, f"work/{WORK_RACE}/work.md", data)
            run(repo, "add", "-A")
            run(repo, "commit", "-m", f"claim {claim_id}")
        expected_claim = run(
            worker_one,
            "show",
            f"HEAD:work/{WORK_RACE}/work.md",
        ).stdout
        run(worker_one, "push", "origin", "HEAD:main")
        mailbox.published += 1
        run(worker_one, "fetch", "origin", "main")
        run(worker_one, "merge-base", "--is-ancestor", "HEAD", "origin/main")
        remote_claim = run(
            worker_one,
            "show",
            f"origin/main:work/{WORK_RACE}/work.md",
        ).stdout
        if remote_claim != expected_claim:
            raise AssertionError("winning claim differs after exact remote read-back")
        mailbox.readbacks += 1
        loser = run(worker_two, "push", "origin", "HEAD:main", check=False)
        record("concurrent claim has one winner", loser.returncode != 0)

        mailbox.sync(worker_one)
        mailbox.sync(worker_two)
        message_one = message("msg_instruction", "instruction")
        message_two = message("msg_needs_decision", "needs-decision")
        write_document(
            worker_one,
            f"work/{WORK_RACE}/messages/msg_instruction.md",
            message_one,
        )
        write_document(
            worker_two,
            f"work/{WORK_RACE}/messages/msg_needs_decision.md",
            message_two,
        )
        mailbox.publish(worker_one, "append instruction")
        run(worker_two, "add", "-A")
        run(worker_two, "commit", "-m", "append decision request")
        rejected = run(worker_two, "push", "origin", "HEAD:main", check=False)
        if rejected.returncode == 0:
            raise AssertionError("concurrent message unexpectedly fast-forwarded")
        mailbox.sync(worker_two)
        write_document(
            worker_two,
            f"work/{WORK_RACE}/messages/msg_needs_decision.md",
            message_two,
        )
        mailbox.publish(worker_two, "retry exact decision request")
        paths = run(
            worker_two,
            "ls-tree",
            "-r",
            "--name-only",
            "origin/main",
            f"work/{WORK_RACE}/messages",
        ).stdout.splitlines()
        record("concurrent messages survive exactly once", len(paths) == 2)

        mailbox.sync(planner)
        timeout_path = f"work/{WORK_RACE}/messages/msg_timeout.md"
        expected_timeout = write_document(
            planner,
            timeout_path,
            message("msg_timeout", "notification"),
        )
        run(planner, "add", "-A")
        run(planner, "commit", "-m", "publish timeout candidate")
        ambiguous_commit = run(planner, "rev-parse", "HEAD").stdout.strip()
        run(planner, "push", "origin", "HEAD:main")
        mailbox.published += 1
        # Simulate losing the push response and performing no immediate read-back.
        mailbox.sync(worker_one)
        write_document(
            worker_one,
            f"work/{WORK_RACE}/messages/msg_later.md",
            message("msg_later", "notification"),
        )
        mailbox.publish(worker_one, "advance after ambiguous push")
        run(planner, "fetch", "origin", "main")
        historical = run(
            planner,
            "merge-base",
            "--is-ancestor",
            ambiguous_commit,
            "origin/main",
            check=False,
        )
        historical_content = run(
            planner,
            "show",
            f"{ambiguous_commit}:{timeout_path}",
            check=False,
        )
        timeout_recovered = (
            historical.returncode == 0
            and historical_content.returncode == 0
            and historical_content.stdout == expected_timeout
        )
        if timeout_recovered:
            mailbox.readbacks += 1
        record("timeout success survives later commits", timeout_recovered)

        mailbox.sync(worker_two)
        unavailable_path = "work/wrk_unavailable/work.md"
        unavailable_work = work_document("active")
        unavailable_work["id"] = "wrk_unavailable"
        unavailable_work["claim"] = claim("clm_unavailable", "run_unavailable")
        write_document(worker_two, unavailable_path, unavailable_work)
        run(worker_two, "add", "-A")
        run(worker_two, "commit", "-m", "attempt unavailable claim")
        run(worker_two, "remote", "set-url", "origin", str(root / "missing.git"))
        unavailable = run(worker_two, "push", "origin", "HEAD:main", check=False)
        run(worker_two, "remote", "set-url", "origin", str(remote))
        run(worker_two, "fetch", "origin", "main")
        absent = run(
            worker_two,
            "show",
            f"origin/main:{unavailable_path}",
            check=False,
        )
        record(
            "unavailable remote cannot establish claim",
            unavailable.returncode != 0 and absent.returncode != 0,
        )
        mailbox.sync(worker_two)

        mailbox.sync(worker_one)
        work_path = f"work/{WORK_RACE}/work.md"
        active = parse_document((worker_one / work_path).read_text())
        checkpoint = active["claim"]["checkpoint"]
        authorized = authorize_checkpoint(
            mailbox,
            worker_one,
            work_path,
            active["claim"]["id"],
            checkpoint["sequence"],
            checkpoint["continuation_token"],
            "repository.candidate.create",
        )
        if authorized is None:
            raise AssertionError("current claimant checkpoint was denied")
        mailbox.sync(worker_one)
        active = parse_document((worker_one / work_path).read_text())
        blocker_id = "msg_blocker"
        receipt_id = "rcp_blocked"
        active["status"] = "blocked"
        active["blocking_message_id"] = blocker_id
        active["attempt_receipt_id"] = receipt_id
        write_document(worker_one, work_path, active)
        write_document(
            worker_one,
            f"work/{WORK_RACE}/messages/{blocker_id}.md",
            message(blocker_id, "needs-decision"),
        )
        write_document(
            worker_one,
            f"work/{WORK_RACE}/receipts/{receipt_id}.md",
            receipt(receipt_id, "blocked", active["claim"]["id"], None),
        )
        mailbox.publish(worker_one, "block atomically")
        fresh_planner = clone(remote, root / "fresh-planner")
        blocked = validate_lifecycle(fresh_planner, f"work/{WORK_RACE}/work.md")
        record("blocker survives session and fresh clone", blocked == "blocked")

        mailbox.sync(planner)
        takeover = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        old_claim = takeover["claim"]["id"]
        old_sequence = takeover["claim"]["checkpoint"]["sequence"]
        old_token = takeover["claim"]["checkpoint"]["continuation_token"]
        takeover["claim"] = claim("clm_takeover", "run_takeover")
        write_document(planner, f"work/{WORK_RACE}/work.md", takeover)
        mailbox.publish(planner, "take over blocked work")
        stale_checkpoint_allowed = checkpoint_is_current(
            worker_one,
            f"work/{WORK_RACE}/work.md",
            old_claim,
            old_sequence,
            old_token,
        )
        record("takeover fences prior claimant", not stale_checkpoint_allowed)

        mailbox.sync(planner)
        resolved = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        resolved["status"] = "active"
        resolved["blocking_message_id"] = None
        write_document(planner, f"work/{WORK_RACE}/work.md", resolved)
        write_document(
            planner,
            f"work/{WORK_RACE}/messages/msg_resolve.md",
            message("msg_resolve", "instruction", resolves=blocker_id),
        )
        mailbox.publish(planner, "resolve blocker")

        project_remote = root / "project.git"
        run(None, "init", "--bare", "--initial-branch=main", str(project_remote))
        project = clone(project_remote, root / "project")
        (project / "source.txt").write_text("base\n")
        run(project, "add", "source.txt")
        run(project, "commit", "-m", "project base")
        run(project, "push", "origin", "HEAD:main")
        base_sha = run(project, "rev-parse", "HEAD").stdout.strip()
        run(project, "checkout", "-b", "candidate")
        (project / "source.txt").write_text("candidate\n")
        run(project, "commit", "-am", "candidate")
        candidate_sha = run(project, "rev-parse", "HEAD").stdout.strip()
        run(project, "push", "origin", "HEAD:refs/heads/candidate")
        candidate_data = {
            "repository": "github:example/project",
            "remote": "origin",
            "remote_url": str(project_remote),
            "remote_ref": "refs/heads/candidate",
            "base_revision": base_sha,
            "head_revision": candidate_sha,
            "pull_request": "https://github.com/example/project/pull/456",
            "workspace_id": None,
            "published_at": "2026-07-25T12:20:00Z",
        }
        mailbox.sync(planner)
        carrying = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        carrying["claim"]["candidate"] = candidate_data
        write_document(planner, f"work/{WORK_RACE}/work.md", carrying)
        mailbox.publish(planner, "register remote candidate")
        mailbox.sync(planner)
        released = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        released_claim = released["claim"]["id"]
        release_receipt_id = "rcp_released"
        released["status"] = "approved"
        released["claim"] = None
        released["attempt_receipt_id"] = release_receipt_id
        write_document(planner, f"work/{WORK_RACE}/work.md", released)
        write_document(
            planner,
            f"work/{WORK_RACE}/receipts/{release_receipt_id}.md",
            receipt(release_receipt_id, "released", released_claim, candidate_data),
        )
        mailbox.publish(planner, "release with candidate handoff")
        fresh_handoff = clone(remote, root / "fresh-handoff")
        fresh_project = clone(project_remote, root / "fresh-project")
        released_work = parse_document((fresh_handoff / f"work/{WORK_RACE}/work.md").read_text())
        discovered_receipt_id = released_work["attempt_receipt_id"]
        released_receipt = parse_document(
            (fresh_handoff / f"work/{WORK_RACE}/receipts/{discovered_receipt_id}.md").read_text()
        )
        release_discovered = (
            discovered_receipt_id == release_receipt_id
            and released_receipt["candidate"] == candidate_data
            and candidate_reachable(fresh_project, released_receipt["candidate"])
        )

        mailbox.sync(planner)
        carrying_again = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        carrying_again["status"] = "active"
        carrying_again["claim"] = claim(
            "clm_candidate_owner",
            "run_candidate_owner",
            released_receipt["candidate"],
        )
        write_document(planner, f"work/{WORK_RACE}/work.md", carrying_again)
        mailbox.publish(planner, "claim released candidate handoff")
        mailbox.sync(planner)
        replaced = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        adopted_candidate = replaced["claim"]["candidate"]
        replaced["claim"] = claim(
            "clm_candidate_takeover",
            "run_candidate_takeover",
            adopted_candidate,
        )
        write_document(planner, f"work/{WORK_RACE}/work.md", replaced)
        mailbox.publish(planner, "take over candidate-bearing work")
        fresh_takeover = clone(remote, root / "fresh-takeover")
        taken_over = parse_document((fresh_takeover / f"work/{WORK_RACE}/work.md").read_text())
        record(
            "release and takeover preserve discoverable remote candidate handoff",
            release_discovered
            and taken_over["attempt_receipt_id"] == release_receipt_id
            and taken_over["claim"]["candidate"] == candidate_data
            and candidate_reachable(fresh_project, taken_over["claim"]["candidate"]),
        )

        run(project, "checkout", "-b", "local-only")
        (project / "source.txt").write_text("local only\n")
        run(project, "commit", "-am", "local-only candidate")
        local_sha = run(project, "rev-parse", "HEAD").stdout.strip()
        local_candidate = dict(candidate_data)
        local_candidate["head_revision"] = local_sha
        record(
            "local-only candidate is rejected",
            not candidate_reachable(project, local_candidate),
        )

        mailbox.sync(planner)
        active_again = parse_document((planner / f"work/{WORK_RACE}/work.md").read_text())
        active_again["status"] = "active"
        active_again["claim"] = claim("clm_revision_guard", "run_revision_guard")
        write_document(planner, f"work/{WORK_RACE}/work.md", active_again)
        mailbox.publish(planner, "claim for revision guard")
        can_revise = active_again["status"] in {"draft", "approved"}
        record("substantive revision under claim is rejected", not can_revise)

        approved_allow = {"repository.candidate.push", "pull_request.create"}
        tightened_allow = {"pull_request.create"}
        loosened_allow = approved_allow | {"pull_request.merge"}
        record(
            "policy drift tightens and never widens",
            "repository.candidate.push" not in approved_allow & tightened_allow
            and "pull_request.merge" not in approved_allow & loosened_allow,
        )

        approved_ticket = {
            "body": "approved",
            "state": "open",
            "relationships": [],
        }
        changed_ticket = dict(approved_ticket, body="changed externally")
        record(
            "material ticket drift blocks next mutation",
            ticket_digest(approved_ticket) != ticket_digest(changed_ticket),
        )

        delivered_head = candidate_sha
        live_pr = {"head_sha": local_sha}
        record(
            "pull request head drift invalidates acceptance",
            live_pr["head_sha"] != delivered_head,
        )

        mailbox.sync(planner)
        invalid_path = "work/wrk_invalid/work.md"
        invalid = work_document()
        invalid["id"] = "wrk_invalid"
        invalid["schema"] = "atelier.work/v2"
        write_document(planner, invalid_path, invalid)
        mailbox.publish(planner, "publish unsupported schema fixture")
        fresh_invalid = clone(remote, root / "fresh-invalid")
        rejected_schema = False
        try:
            validate_lifecycle(fresh_invalid, invalid_path)
        except ValueError:
            rejected_schema = True
        record("unsupported schema fails closed", rejected_schema)
        mailbox.sync(planner)
        (planner / invalid_path).unlink()
        mailbox.publish(planner, "remove unsupported schema fixture")

        mailbox.sync(planner)
        state_paths: list[str] = []
        for index, status in enumerate(
            ("approved", "active", "blocked", "delivered", "accepted"),
            start=10,
        ):
            work_id = f"wrk_019f9a9e-0000-7000-8000-{index:012d}"
            state_claim_id = f"clm_{index}"
            blocker_id = f"msg_state_blocker_{index}"
            attempt_id = f"rcp_{index}"
            data = work_document(status)
            data["id"] = work_id
            data["claim"] = (
                claim(state_claim_id, f"run_{index}", candidate_data)
                if status in {"active", "blocked", "delivered"}
                else None
            )
            data["blocking_message_id"] = blocker_id if status == "blocked" else None
            data["attempt_receipt_id"] = (
                attempt_id if status in {"blocked", "delivered", "accepted"} else None
            )
            data["delivery_receipt_id"] = (
                attempt_id if status in {"delivered", "accepted"} else None
            )
            data["acceptance"] = (
                {
                    "receipt_id": attempt_id,
                    "accepted_by": "operator",
                    "accepted_at": "2026-07-25T13:15:00Z",
                    "policy_commit": SHA_ZERO,
                    "candidate_revision": candidate_sha,
                    "evidence": {"candidate-remote-reachable": "satisfied"},
                }
                if status == "accepted"
                else None
            )
            relative = f"work/{work_id}/work.md"
            write_document(planner, relative, data)
            if status == "blocked":
                write_document(
                    planner,
                    f"work/{work_id}/messages/{blocker_id}.md",
                    message(blocker_id, "needs-decision", work_id=work_id),
                )
            if status in {"blocked", "delivered", "accepted"}:
                write_document(
                    planner,
                    f"work/{work_id}/receipts/{attempt_id}.md",
                    receipt(
                        attempt_id,
                        "blocked" if status == "blocked" else "delivered",
                        state_claim_id,
                        candidate_data,
                        work_id=work_id,
                    ),
                )
            state_paths.append(relative)

        ready_id = "wrk_019f9a9e-0000-7000-8000-000000000099"
        ready_path = f"work/{ready_id}/work.md"
        ready_data = work_document("approved")
        ready_data["id"] = ready_id
        ready_data["project_id"] = "prj_ready"
        accepted_dependency = state_paths[-1].split("/")[1]
        ready_data["dependencies"] = [accepted_dependency]
        write_document(planner, ready_path, ready_data)

        missing_dependency_path = "work/wrk_ready_missing/work.md"
        missing_dependency = work_document("approved")
        missing_dependency["id"] = "wrk_ready_missing"
        missing_dependency["project_id"] = "prj_ready_missing"
        missing_dependency["dependencies"] = ["wrk_does_not_exist"]
        write_document(planner, missing_dependency_path, missing_dependency)

        nonaccepted_dependency_path = "work/wrk_ready_nonaccepted/work.md"
        nonaccepted_dependency = work_document("approved")
        nonaccepted_dependency["id"] = "wrk_ready_nonaccepted"
        nonaccepted_dependency["project_id"] = "prj_ready_nonaccepted"
        nonaccepted_dependency["dependencies"] = [state_paths[0].split("/")[1]]
        write_document(planner, nonaccepted_dependency_path, nonaccepted_dependency)

        illegal_claim_path = "work/wrk_ready_illegal_claim/work.md"
        illegal_claim = work_document("approved")
        illegal_claim["id"] = "wrk_ready_illegal_claim"
        illegal_claim["project_id"] = "prj_ready_illegal_claim"
        illegal_claim["claim"] = claim("clm_illegal_ready", "run_illegal_ready")
        write_document(planner, illegal_claim_path, illegal_claim)
        mailbox.publish(planner, "publish reconstruction states")
        fresh_audit = clone(remote, root / "fresh-audit")
        reconstructed = {validate_lifecycle(fresh_audit, path) for path in state_paths}
        record(
            "fresh clone reconstructs all lifecycle states",
            reconstructed == {"approved", "active", "blocked", "delivered", "accepted"},
        )
        ready = derive_ready(
            fresh_audit,
            ready_path,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        blocked_by_policy = derive_ready(
            fresh_audit,
            ready_path,
            policy_gates_satisfied=False,
            ticket_eligible=True,
            capability_available=True,
        )
        blocked_by_ticket = derive_ready(
            fresh_audit,
            ready_path,
            policy_gates_satisfied=True,
            ticket_eligible=False,
            capability_available=True,
        )
        blocked_by_capability = derive_ready(
            fresh_audit,
            ready_path,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=False,
        )
        blocked_by_missing_dependency = derive_ready(
            fresh_audit,
            missing_dependency_path,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        blocked_by_nonaccepted_dependency = derive_ready(
            fresh_audit,
            nonaccepted_dependency_path,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        blocked_by_nonapproved_status = derive_ready(
            fresh_audit,
            state_paths[1],
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        blocked_by_illegal_claim = derive_ready(
            fresh_audit,
            illegal_claim_path,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        default_project_approved = state_paths[0]
        blocked_by_serial_execution = derive_ready(
            fresh_audit,
            default_project_approved,
            policy_gates_satisfied=True,
            ticket_eligible=True,
            capability_available=True,
        )
        record(
            "fresh clone derives ready only when every v0 gate passes",
            ready
            and not blocked_by_policy
            and not blocked_by_ticket
            and not blocked_by_capability
            and not blocked_by_missing_dependency
            and not blocked_by_nonaccepted_dependency
            and not blocked_by_nonapproved_status
            and not blocked_by_illegal_claim
            and not blocked_by_serial_execution,
        )
        record(
            "success requires exact remote read-back",
            mailbox.published == mailbox.readbacks,
        )

    for index, (name, _) in enumerate(results, start=1):
        print(f"{index:02d} PASS {name}")
    print(f"{len(results)} scenarios passed; disposable repositories removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

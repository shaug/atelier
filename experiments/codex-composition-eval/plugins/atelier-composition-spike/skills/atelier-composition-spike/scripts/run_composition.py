#!/usr/bin/env python3
"""Prepare, transport, and verify host-native composition evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

CAPABILITY = "agent-scripts.implement-ticket/delegated-execution/v1"


@dataclass(frozen=True)
class GitFixture:
    """One disposable repository and bare remote."""

    repository: Path
    remote: Path
    base_sha: str


def write_json(path: Path, value: object) -> None:
    """Write deterministic JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_object(path: Path) -> dict[str, object]:
    """Read one JSON object."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def read_array(path: Path) -> list[object]:
    """Read one JSON array."""
    value = json.loads(path.read_text())
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected JSON array")
    return value


def digest(path: Path) -> str:
    """Return one file's SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    """Hash every regular file beneath one preserved package root."""
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run(command: list[str], *, cwd: Path | None = None, stdin: str | None = None) -> str:
    """Run one command and return standard output."""
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def installed_skill(workspace: Path) -> Path:
    """Resolve the independent project-local Agent Scripts install."""
    root = (workspace / ".agents" / "skills" / "implement-ticket").resolve()
    capability = root / "references" / "delegated-execution" / "capability.json"
    if not capability.is_file():
        raise ValueError(f"delegated capability is missing: {capability}")
    return root


def load_validator(skill_root: Path) -> ModuleType:
    """Load the validator owned by the independent Agent Scripts install."""
    path = skill_root / "references" / "delegated-execution" / "validate.py"
    spec = importlib.util.spec_from_file_location("delegated_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_fixture(root: Path) -> GitFixture:
    """Create fixture infrastructure without creating implementation state."""
    repository = root / "repository"
    remote = root / "remote.git"
    run(["git", "init", "--bare", str(remote)])
    run(["git", "init", str(repository)])
    run(
        ["git", "config", "user.email", "atelier-spike@example.invalid"],
        cwd=repository,
    )
    run(["git", "config", "user.name", "Atelier Spike"], cwd=repository)
    (repository / "README.md").write_text("# Composition fixture\n")
    run(["git", "add", "README.md"], cwd=repository)
    run(["git", "commit", "-m", "fixture: create base"], cwd=repository)
    run(["git", "branch", "-M", "main"], cwd=repository)
    run(["git", "remote", "add", "origin", str(remote.resolve())], cwd=repository)
    run(["git", "push", "origin", "main"], cwd=repository)
    return GitFixture(
        repository=repository,
        remote=remote,
        base_sha=run(["git", "rev-parse", "HEAD"], cwd=repository),
    )


def invocation(
    fixture: GitFixture,
    checkpoint_command: list[str],
    case: str,
) -> dict[str, object]:
    """Build one worker input without performing worker actions."""
    invocation_id = f"atelier-composition-{case}"
    return {
        "schema": "agent-scripts.implement-ticket/delegated-invocation/v1",
        "capability": CAPABILITY,
        "invocation_id": invocation_id,
        "ticket": {
            "provider": "github",
            "id": f"SPIKE-{case.upper()}",
            "url": f"https://github.invalid/atelier/spike/issues/{case}",
            "observation": f"sha256:ticket-{case}",
        },
        "repository": {
            "identity": "github:atelier/composition-spike",
            "remote_url": str(fixture.remote.resolve()),
            "base_ref": "refs/heads/main",
            "base_sha": fixture.base_sha,
        },
        "work": {
            "id": f"wrk_composition_{case}",
            "revision": 1,
            "approval_evidence": f"fixture-approval-{case}",
            "intent": "Prove Agent Scripts drives one delegated fixture run",
            "scope": ["Publish one candidate and attempt one PR fixture"],
            "non_goals": ["Mutate GitHub", "Implement production Atelier"],
            "constraints": ["Obey every delegated checkpoint response"],
            "done_definition": ["Write a valid result.json and execution log"],
        },
        "validation": ["fixture validation"],
        "review": {
            "independent": True,
            "unresolved_feedback_required": True,
        },
        "authority": {
            "allow": [
                "repository.candidate.create",
                "repository.candidate.push",
                "pull_request.create",
            ]
        },
        "desired_outcome": "ready_pr",
        "accepted_terminal_states": ["ready_pr", "blocked", "requires_epic"],
        "checkpoint": {
            "command": checkpoint_command,
            "last_sequence": 0,
            "continuation_token": "token-0",
        },
    }


def prepare(workspace: Path, output: Path, case: str) -> dict[str, object]:
    """Prepare a case without performing delegated implementation work."""
    if output.exists():
        raise ValueError(f"refusing to overwrite case: {output}")
    output.mkdir(parents=True)
    skill_root = installed_skill(workspace)
    validator = load_validator(skill_root)
    fixture = git_fixture(output)
    state_path = output / "checkpoint-state.json"
    checkpoint = Path(__file__).with_name("checkpoint.py").resolve()
    command = [
        sys.executable,
        str(checkpoint),
        "--implement-ticket-root",
        str(skill_root),
        "--state",
        str(state_path),
    ]
    source = invocation(fixture, command, case)
    errors = validator.validate("invocation", source)
    if errors:
        raise ValueError("; ".join(errors))
    repository = source["repository"]
    ticket = source["ticket"]
    work = source["work"]
    authority = source["authority"]
    assert isinstance(repository, dict)
    assert isinstance(ticket, dict)
    assert isinstance(work, dict)
    assert isinstance(authority, dict)
    write_json(
        state_path,
        {
            "invocation_id": source["invocation_id"],
            "capability": source["capability"],
            "ticket_observation": ticket["observation"],
            "repository": repository,
            "work_id": work["id"],
            "work_revision": work["revision"],
            "approval_evidence": work["approval_evidence"],
            "last_sequence": 0,
            "continuation_token": "token-0",
            "allow_actions": authority["allow"],
            "deny_actions": ["pull_request.create"] if case == "denied" else [],
            "ledger": [],
        },
    )
    write_json(output / "invocation.json", source)
    write_json(
        output / "fixture.json",
        {
            "case": case,
            "repository": str(fixture.repository),
            "remote": str(fixture.remote),
            "result_path": str(output / "result.json"),
            "execution_log_path": str(output / "execution-log.json"),
            "worker_observation_path": str(output / "worker-observation.json"),
            "review_input_path": str(output / "review-input.json"),
            "review_request_path": str(output / "review-request.json"),
            "review_complete_path": str(output / "review-complete.json"),
            "review_final_path": str(output / "review-final.json"),
            "review_events_path": str(output / "review-events.jsonl"),
            "review_launch_path": str(output / "review-launch.json"),
            "pull_request_marker": str(output / "pull-request-created"),
        },
    )
    return {
        "case": case,
        "case_root": str(output),
        "invocation": str(output / "invocation.json"),
        "repository": str(fixture.repository),
    }


def exchange(invocation_path: Path, request_path: Path, response_path: Path) -> None:
    """Transport one worker-authored request to the invocation's command."""
    source = read_object(invocation_path)
    checkpoint = source["checkpoint"]
    assert isinstance(checkpoint, dict)
    command = checkpoint["command"]
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("invocation checkpoint command is invalid")
    request = read_object(request_path)
    response = json.loads(run(command, stdin=json.dumps(request)))
    if not isinstance(response, dict):
        raise ValueError("checkpoint response is not an object")
    write_json(response_path, response)


def probe_checkpoint(
    skill_root: Path,
    state_path: Path,
    request_path: Path,
    response_path: Path,
) -> None:
    """Probe the current checkpoint implementation against preserved state."""
    command = [
        sys.executable,
        str(Path(__file__).with_name("checkpoint.py")),
        "--implement-ticket-root",
        str(skill_root),
        "--state",
        str(state_path),
    ]
    request = read_object(request_path)
    response = json.loads(run(command, stdin=json.dumps(request)))
    if not isinstance(response, dict):
        raise ValueError("checkpoint probe response is not an object")
    write_json(response_path, response)


def verify_isolated_review(
    case_root: Path,
    source: dict[str, object],
    result: dict[str, object],
    fixture: dict[str, object],
    candidate: dict[str, object],
    host_launch: dict[str, object],
) -> None:
    """Verify that a fresh read-only process reviewed the exact candidate."""
    input_path = case_root / "review-input.json"
    final_path = case_root / "review-final.json"
    events_path = case_root / "review-events.jsonl"
    launch_path = case_root / "review-launch.json"
    review_input = read_object(input_path)
    review_final = read_object(final_path)
    launch = read_object(launch_path)
    request = read_object(case_root / "review-request.json")
    completion = read_object(case_root / "review-complete.json")
    if (
        request.get("schema") != "atelier.composition/review-request/v1"
        or request.get("review_input") != str(input_path.resolve())
        or request.get("review_input_sha256") != digest(input_path)
        or completion.get("schema") != "atelier.composition/review-complete/v1"
        or completion.get("request_id") != request.get("request_id")
        or completion.get("exit_code") != 0
        or launch.get("request_id") != request.get("request_id")
    ):
        raise AssertionError("host review request, launch, and completion are not causally bound")
    supervisor = host_launch.get("review_supervisor")
    if not isinstance(supervisor, dict) or (
        supervisor.get("kind") != "one-shot-file-request"
        or Path(str(supervisor.get("request_path"))).resolve()
        != (case_root / "review-request.json").resolve()
    ):
        raise AssertionError("worker launch lacks the one-shot host review supervisor")
    raw_lines = [line for line in events_path.read_text().splitlines() if line.strip()]
    if not raw_lines:
        raise AssertionError("isolated review transcript is missing")
    events = [json.loads(line) for line in raw_lines]
    if not all(isinstance(event, dict) for event in events):
        raise AssertionError("isolated review transcript is malformed")
    if not any(event.get("type") == "thread.started" for event in events):
        raise AssertionError("isolated review transcript has no fresh thread")
    git_commands = [
        str(event.get("item", {}).get("command", ""))
        for event in events
        if isinstance(event.get("item"), dict) and event["item"].get("type") == "command_execution"
    ]
    if not any("git" in command for command in git_commands):
        raise AssertionError("isolated reviewer did not inspect the candidate with Git")
    messages = [
        event["item"]["text"]
        for event in events
        if isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    if not messages or json.loads(messages[-1]) != review_final:
        raise AssertionError("review final output differs from the raw reviewer transcript")
    expected_input_keys = {
        "schema",
        "invocation_id",
        "ticket_id",
        "intent",
        "repository_identity",
        "repository_path",
        "candidate_git_dir",
        "base_sha",
        "candidate_sha",
        "candidate_ref",
        "validation",
    }
    if set(review_input) != expected_input_keys:
        raise AssertionError("review input has an unexpected shape")
    repository = source["repository"]
    ticket = source["ticket"]
    work = source["work"]
    assert isinstance(repository, dict)
    assert isinstance(ticket, dict)
    assert isinstance(work, dict)
    expected_input = {
        "schema": "atelier.composition/review-input/v1",
        "invocation_id": source["invocation_id"],
        "ticket_id": ticket["id"],
        "intent": work["intent"],
        "repository_identity": repository["identity"],
        "repository_path": str(Path(str(fixture["repository"])).resolve()),
        "base_sha": repository["base_sha"],
        "candidate_sha": candidate["head_sha"],
        "candidate_ref": candidate["remote_ref"],
    }
    for field, expected in expected_input.items():
        if review_input[field] != expected:
            raise AssertionError(f"review input {field} does not match the invocation")
    validation = review_input["validation"]
    if not isinstance(validation, list) or not validation:
        raise AssertionError("review input lacks validation evidence")
    if not any(
        isinstance(item, dict)
        and item.get("name") == "fixture validation"
        and item.get("outcome") == "passed"
        and item.get("candidate_sha") == candidate["head_sha"]
        for item in validation
    ):
        raise AssertionError("review input lacks exact-head fixture validation")
    git_dir = Path(str(review_input["candidate_git_dir"])).resolve()
    observed_head = run(
        ["git", f"--git-dir={git_dir}", "rev-parse", f"{review_input['candidate_ref']}^{{commit}}"]
    )
    if observed_head != candidate["head_sha"]:
        raise AssertionError("review Git directory does not resolve the exact candidate")
    run(
        [
            "git",
            f"--git-dir={git_dir}",
            "merge-base",
            "--is-ancestor",
            str(review_input["base_sha"]),
            str(review_input["candidate_sha"]),
        ]
    )
    expected_final_keys = {
        "verdict",
        "comparison_base_sha",
        "candidate_sha",
        "findings",
        "summary",
    }
    if set(review_final) != expected_final_keys:
        raise AssertionError("isolated review output has an unexpected shape")
    if (
        review_final["verdict"] != "clean"
        or review_final["comparison_base_sha"] != candidate["base_sha"]
        or review_final["candidate_sha"] != candidate["head_sha"]
        or review_final["findings"] != []
        or not str(review_final["summary"]).strip()
    ):
        raise AssertionError("isolated reviewer did not cleanly pass the exact candidate")
    command = launch["command"]
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise AssertionError("isolated review launch command is malformed")
    required_arguments = {"exec", "--ephemeral", "--json", "--sandbox", "read-only"}
    if not required_arguments.issubset(command) or "--output-schema" not in command:
        raise AssertionError("isolated review was not launched with the required host boundary")
    host_command = host_launch["command"]
    if not isinstance(host_command, list) or not host_command:
        raise AssertionError("worker host launch command is malformed")
    executable = Path(command[0]).resolve()
    if (
        Path(str(host_command[0])).resolve() != executable
        or launch["codex_executable_sha256"] != digest(executable)
        or host_launch["codex_executable_sha256"] != digest(executable)
        or launch["codex_version"] != host_launch["codex_version"]
    ):
        raise AssertionError("worker and reviewer did not use the same preserved Codex package")
    schema = Path(__file__).resolve().parents[1] / "references" / "reviewer-output.schema.json"
    if launch["review_input_sha256"] != digest(input_path):
        raise AssertionError("review launch input hash does not match preserved input")
    if launch["schema_sha256"] != digest(schema):
        raise AssertionError("review launch schema hash does not match evaluated package")
    reviews = result["reviews"]
    feedback = result["feedback"]
    if not isinstance(reviews, list) or not any(
        isinstance(item, dict)
        and item.get("outcome") == "passed"
        and item.get("candidate_sha") == candidate["head_sha"]
        for item in reviews
    ):
        raise AssertionError("terminal result does not record the isolated exact-head review")
    if not isinstance(feedback, dict) or (
        feedback.get("candidate_sha") != candidate["head_sha"]
        or feedback.get("unresolved_material_count") != 0
    ):
        raise AssertionError("terminal feedback does not match the isolated review")


def verify_case(
    workspace: Path,
    case_root: Path,
    expected_case: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Verify worker results against independent host and durable evidence."""
    skill_root = installed_skill(workspace)
    validator = load_validator(skill_root)
    source = read_object(case_root / "invocation.json")
    result = read_object(case_root / "result.json")
    state = read_object(case_root / "checkpoint-state.json")
    fixture = read_object(case_root / "fixture.json")
    observation = read_object(case_root / "worker-observation.json")
    execution_log = read_array(case_root / "execution-log.json")
    launch = read_object(case_root / "host-launch.json")
    raw_events = (case_root / "codex-events.jsonl").read_text()
    final_output = (case_root / "codex-final.txt").read_text()
    if not raw_events.strip() or not final_output.strip() or not execution_log:
        raise AssertionError("fresh host transcript or worker execution evidence is missing")
    if "agent-scripts" not in json.dumps(launch["plugin_list"]):
        raise AssertionError("fresh host launch did not observe the Agent Scripts plugin")
    errors = validator.validate_result_checkpoint_state(
        source,
        result,
        state["last_sequence"],
        state["continuation_token"],
    )
    if errors:
        raise AssertionError(errors)
    candidate = result["candidate"]
    if not isinstance(candidate, dict):
        raise AssertionError("worker returned no published candidate")
    verify_isolated_review(case_root, source, result, fixture, candidate, launch)
    observed = run(["git", "ls-remote", candidate["remote_url"], candidate["remote_ref"]]).split()[
        0
    ]
    if observed != candidate["head_sha"]:
        raise AssertionError("candidate is not reachable from its exact remote ref")
    remote = Path(str(fixture["remote"]))
    deliverable = run(
        [
            "git",
            f"--git-dir={remote}",
            "show",
            f"{candidate['head_sha']}:DELIVERABLE.md",
        ]
    )
    if str(source["invocation_id"]) not in deliverable or "implement-ticket" not in deliverable:
        raise AssertionError("candidate does not contain the delegated deliverable")
    run(
        [
            "git",
            f"--git-dir={remote}",
            "merge-base",
            "--is-ancestor",
            str(source["repository"]["base_sha"]),
            str(candidate["head_sha"]),
        ]
    )
    ledger = state["ledger"]
    assert isinstance(ledger, list)
    if [entry["sequence"] for entry in ledger if isinstance(entry, dict)] != list(
        range(1, len(ledger) + 1)
    ):
        raise AssertionError("durable checkpoint ledger is not contiguous")
    pre_actions = {
        entry["action"]
        for entry in ledger
        if isinstance(entry, dict) and entry["phase"] == "pre_external_mutation"
    }
    expected_actions = {
        "repository.candidate.create",
        "repository.candidate.push",
    }
    if expected_case == "success":
        expected_actions.add("pull_request.create")
    if pre_actions != expected_actions or pre_actions != set(result["authority_used"]):
        raise AssertionError("terminal authority does not equal expected durable allowances")
    acknowledgements = [
        entry
        for entry in ledger
        if isinstance(entry, dict) and entry["phase"] == "candidate_published"
    ]
    if len(acknowledgements) != 1 or (
        acknowledgements[0]["acknowledged_candidate_sha"] != candidate["head_sha"]
    ):
        raise AssertionError("published candidate lacks exact durable acknowledgement")
    marker = Path(str(fixture["pull_request_marker"]))
    publication = candidate["publication"]
    assert isinstance(publication, dict)
    pull_requests = publication["pull_requests"]
    assert isinstance(pull_requests, list)
    if expected_case == "success":
        if result["terminal_state"] != "ready_pr" or not marker.is_file():
            raise AssertionError("successful worker did not produce the PR fixture")
        if len(pull_requests) != 1 or read_object(marker) != pull_requests[0]:
            raise AssertionError("PR fixture marker differs from the terminal result")
    elif (
        result["terminal_state"] != "blocked"
        or result["blocking_reason"] is None
        or marker.exists()
        or pull_requests
    ):
        raise AssertionError("denied worker performed or misreported the denied action")
    skill_path = Path(str(observation["skill_path"])).resolve()
    expected_fragment = "/plugins/cache/agent-scripts/agent-scripts/"
    if expected_fragment not in str(skill_path):
        raise AssertionError("worker did not use the independently installed plugin skill")
    if observation["invocation_name"] != "implement-ticket":
        raise AssertionError("worker did not invoke implement-ticket by stable name")
    installed_hash = digest(skill_root / "SKILL.md")
    capability_path = skill_root / "references" / "delegated-execution" / "capability.json"
    if digest(skill_path) != installed_hash or observation["skill_sha256"] != installed_hash:
        raise AssertionError("worker skill differs from the validated capability install")
    if observation["capability_sha256"] != digest(capability_path):
        raise AssertionError("worker capability differs from the validated capability install")
    execution_text = json.dumps(execution_log)
    if not all(term in execution_text for term in ("checkpoint", "git push", "review-request")):
        raise AssertionError("worker execution log omits required delegated operations")
    return source, result


def negative_checks(
    workspace: Path,
    success_root: Path,
    denied_root: Path,
) -> list[dict[str, object]]:
    """Run coordinator and consumer rejection checks after real worker runs."""
    skill_root = installed_skill(workspace)
    validator = load_validator(skill_root)
    capability_path = skill_root / "references" / "delegated-execution" / "capability.json"
    capability = read_object(capability_path)
    success_source = read_object(success_root / "invocation.json")
    success_result = read_object(success_root / "result.json")
    denied_source = read_object(denied_root / "invocation.json")
    denied_result = read_object(denied_root / "result.json")
    checks: list[dict[str, object]] = []

    malformed = copy.deepcopy(capability)
    malformed["atelier"] = True
    checks.append(
        {
            "name": "malformed capability is rejected",
            "passed": "$.atelier: unknown property" in validator.validate("capability", malformed),
        }
    )

    excess = copy.deepcopy(success_result)
    excess["authority_used"].append("pull_request.merge")
    checks.append(
        {
            "name": "excess terminal authority is rejected",
            "passed": any(
                "exceeds invocation" in error
                for error in validator.validate_result_for_invocation(success_source, excess)
            ),
        }
    )

    candidate = success_result["candidate"]
    assert isinstance(candidate, dict)
    mismatch_request = {
        "schema": "agent-scripts.implement-ticket/checkpoint-request/v1",
        "capability": CAPABILITY,
        "invocation_id": success_source["invocation_id"],
        "continuation_token": "token-a",
        "sequence": 1,
        "phase": "candidate_published",
        "action": "repository.candidate.push",
        "ticket_observation": success_source["ticket"]["observation"],
        "candidate": {
            key: candidate[key]
            for key in ("repository", "remote_url", "remote_ref", "base_sha", "head_sha")
        },
        "proposed_effect": "Acknowledge a mismatched candidate",
    }
    mismatch_response = {
        "schema": "agent-scripts.implement-ticket/checkpoint-response/v1",
        "invocation_id": success_source["invocation_id"],
        "request_sequence": 1,
        "prior_continuation_token": "token-a",
        "continuation_token": "token-b",
        "decision": "allow",
        "reason": None,
        "acknowledged_candidate_sha": success_source["repository"]["base_sha"],
    }
    checks.append(
        {
            "name": "candidate acknowledgement mismatch is rejected",
            "passed": any(
                "does not match published candidate" in error
                for error in validator.validate_checkpoint_exchange(
                    mismatch_request, mismatch_response
                )
            ),
        }
    )

    state_path = denied_root / "checkpoint-state.json"
    before = read_object(state_path)
    foreign_request = {
        "schema": "agent-scripts.implement-ticket/checkpoint-request/v1",
        "capability": CAPABILITY,
        "invocation_id": "foreign-invocation",
        "continuation_token": before["continuation_token"],
        "sequence": int(before["last_sequence"]) + 1,
        "phase": "pre_external_mutation",
        "action": "repository.candidate.create",
        "ticket_observation": "sha256:foreign-ticket",
        "candidate": None,
        "proposed_effect": "Consume another invocation's allowance",
    }
    foreign_request_path = denied_root / "foreign-request.json"
    foreign_response_path = denied_root / "foreign-response.json"
    write_json(foreign_request_path, foreign_request)
    probe_checkpoint(
        skill_root,
        state_path,
        foreign_request_path,
        foreign_response_path,
    )
    foreign_response = read_object(foreign_response_path)
    checks.append(
        {
            "name": "foreign invocation cannot consume checkpoint state",
            "passed": foreign_response["decision"] == "deny" and read_object(state_path) == before,
        }
    )
    authority_request = {
        "schema": "agent-scripts.implement-ticket/checkpoint-request/v1",
        "capability": CAPABILITY,
        "invocation_id": denied_source["invocation_id"],
        "continuation_token": before["continuation_token"],
        "sequence": int(before["last_sequence"]) + 1,
        "phase": "pre_external_mutation",
        "action": "ticket.update",
        "ticket_observation": denied_source["ticket"]["observation"],
        "candidate": None,
        "proposed_effect": "Mutate a ticket outside delegated authority",
    }
    authority_request_path = denied_root / "excess-authority-request.json"
    authority_response_path = denied_root / "excess-authority-response.json"
    write_json(authority_request_path, authority_request)
    probe_checkpoint(
        skill_root,
        state_path,
        authority_request_path,
        authority_response_path,
    )
    authority_response = read_object(authority_response_path)
    checks.append(
        {
            "name": "excess action is denied before mutation",
            "passed": authority_response["decision"] == "deny"
            and "invocation authority excludes ticket.update" in str(authority_response["reason"])
            and read_object(state_path) == before,
        }
    )
    stale_request = {
        "schema": "agent-scripts.implement-ticket/checkpoint-request/v1",
        "capability": CAPABILITY,
        "invocation_id": denied_source["invocation_id"],
        "continuation_token": before["continuation_token"],
        "sequence": before["last_sequence"],
        "phase": "pre_external_mutation",
        "action": "repository.candidate.create",
        "ticket_observation": denied_source["ticket"]["observation"],
        "candidate": None,
        "proposed_effect": "Replay an already consumed sequence",
    }
    stale_request_path = denied_root / "stale-request.json"
    stale_response_path = denied_root / "stale-response.json"
    write_json(stale_request_path, stale_request)
    probe_checkpoint(
        skill_root,
        state_path,
        stale_request_path,
        stale_response_path,
    )
    stale_response = read_object(stale_response_path)
    checks.append(
        {
            "name": "stale sequence cannot consume checkpoint state",
            "passed": stale_response["decision"] == "deny" and read_object(state_path) == before,
        }
    )

    denied_candidate = denied_result["candidate"]
    assert isinstance(denied_candidate, dict)
    foreign_candidate = {
        key: denied_candidate[key]
        for key in ("repository", "remote_url", "remote_ref", "base_sha", "head_sha")
    }
    foreign_candidate["remote_url"] = "/tmp/foreign-remote.git"
    repository_request = {
        "schema": "agent-scripts.implement-ticket/checkpoint-request/v1",
        "capability": CAPABILITY,
        "invocation_id": denied_source["invocation_id"],
        "continuation_token": before["continuation_token"],
        "sequence": int(before["last_sequence"]) + 1,
        "phase": "pre_external_mutation",
        "action": "repository.candidate.push",
        "ticket_observation": denied_source["ticket"]["observation"],
        "candidate": foreign_candidate,
        "proposed_effect": "Publish a candidate for another repository",
    }
    repository_request_path = denied_root / "foreign-repository-request.json"
    repository_response_path = denied_root / "foreign-repository-response.json"
    write_json(repository_request_path, repository_request)
    probe_checkpoint(
        skill_root,
        state_path,
        repository_request_path,
        repository_response_path,
    )
    repository_response = read_object(repository_response_path)
    checks.append(
        {
            "name": "foreign repository cannot consume checkpoint state",
            "passed": repository_response["decision"] == "deny"
            and read_object(state_path) == before,
        }
    )
    return checks


def verify(workspace: Path, success_root: Path, denied_root: Path, output: Path) -> int:
    """Verify both worker runs and persist a compact evaluation summary."""
    checks: list[dict[str, object]] = []
    try:
        verify_case(workspace, success_root, "success")
        checks.append({"name": "host worker delivers allowed case", "passed": True})
    except Exception as error:  # noqa: BLE001 - preserve every evaluation failure.
        checks.append(
            {"name": "host worker delivers allowed case", "passed": False, "error": str(error)}
        )
    try:
        verify_case(workspace, denied_root, "denied")
        checks.append({"name": "host worker obeys denied mutation", "passed": True})
    except Exception as error:  # noqa: BLE001 - preserve every evaluation failure.
        checks.append(
            {"name": "host worker obeys denied mutation", "passed": False, "error": str(error)}
        )
    try:
        checks.extend(negative_checks(workspace, success_root, denied_root))
    except Exception as error:  # noqa: BLE001 - preserve every evaluation failure.
        checks.append({"name": "negative protocol checks", "passed": False, "error": str(error)})
    failed = [str(check["name"]) for check in checks if not check["passed"]]
    skill_root = installed_skill(workspace)
    this_skill = Path(__file__).resolve().parents[1] / "SKILL.md"
    summary = {
        "capability_id": CAPABILITY,
        "agent_scripts_skill_sha256": digest(skill_root / "SKILL.md"),
        "atelier_skill_sha256": digest(this_skill),
        "scenario_count": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "failed_scenarios": failed,
        "evidence_path": str(output.resolve()),
        "boundary_observation": (
            "Fresh Codex workers used the independently installed Agent Scripts "
            "plugin skill; Atelier prepared and verified but did not perform their work."
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    plugin_root = Path(__file__).resolve().parents[3]
    checkpoint_path = Path(__file__).with_name("checkpoint.py").resolve()
    worker_skill_roots = sorted(
        {
            str(
                Path(str(read_object(root / "worker-observation.json")["skill_path"]))
                .resolve()
                .parent
            )
            for root in (success_root, denied_root)
        }
    )
    write_json(
        output / "package-provenance.json",
        {
            "executing_atelier_package_root": str(plugin_root),
            "executing_atelier_package_files": tree_manifest(plugin_root),
            "negative_probe_checkpoint": {
                "path": str(checkpoint_path),
                "sha256": digest(checkpoint_path),
                "statement": (
                    "Negative probes invoked the checkpoint from the executing preserved "
                    "package; this hash must equal the worker invocation checkpoint hash."
                ),
            },
            "agent_scripts_validation_root": str(skill_root),
            "agent_scripts_validation_files": tree_manifest(skill_root),
            "worker_agent_scripts_skill_roots": [
                {"path": path, "files": tree_manifest(Path(path))} for path in worker_skill_roots
            ],
        },
    )
    write_json(output / "checks.json", checks)
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    """Parse subcommands."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--workspace", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    prepare_parser.add_argument("--case", required=True, choices=("success", "denied"))
    exchange_parser = commands.add_parser("exchange")
    exchange_parser.add_argument("--invocation", required=True, type=Path)
    exchange_parser.add_argument("--request", required=True, type=Path)
    exchange_parser.add_argument("--response", required=True, type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--workspace", required=True, type=Path)
    verify_parser.add_argument("--success", required=True, type=Path)
    verify_parser.add_argument("--denied", required=True, type=Path)
    verify_parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Dispatch one composition-evaluation operation."""
    args = parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(args.workspace.resolve(), args.output.resolve(), args.case)))
        return 0
    if args.command == "exchange":
        exchange(args.invocation.resolve(), args.request.resolve(), args.response.resolve())
        return 0
    return verify(
        args.workspace.resolve(),
        args.success.resolve(),
        args.denied.resolve(),
        args.output.resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())

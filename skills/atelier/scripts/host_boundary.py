#!/usr/bin/env python3
"""Validate Atelier's fail-closed Codex host boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESCRIPTOR = ROOT / "references" / "host-capability.json"
EXPECTED_DESCRIPTOR_KEYS = {
    "schema",
    "reference_host",
    "delegated_capability",
    "delegated_authority_actions",
    "accepted_terminal_states",
    "delegated_skill",
    "native_state",
    "native_state_access",
    "fallback_to_copied_workflows",
}
EXPECTED_DELEGATED_KEYS = {
    "stable_name",
    "frontmatter_name",
    "skill_sha256",
    "capability_manifest",
    "capability_manifest_sha256",
}
EXPECTED_NATIVE_STATE_KEYS = {
    "access",
    "connector",
    "observation_schema",
    "required_operations",
}
CAPABILITY_FILE_FIELDS = (
    "contract",
    "invocation_schema",
    "checkpoint_request_schema",
    "checkpoint_response_schema",
    "result_schema",
    "validator",
)


class HostBoundaryError(ValueError):
    """A host prerequisite or observation is not trustworthy."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HostBoundaryError(f"{label} unreadable: {error}") from error
    if not isinstance(value, dict):
        raise HostBoundaryError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise HostBoundaryError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise HostBoundaryError(f"{label} unknown fields: {', '.join(unknown)}")


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _resolve_schema_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not reference:
        return schema
    prefix = "#/$defs/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise HostBoundaryError(f"unsupported observation schema reference: {reference}")
    name = reference.removeprefix(prefix)
    try:
        resolved = root["$defs"][name]
    except KeyError as error:
        raise HostBoundaryError(f"missing observation schema definition: {name}") from error
    if not isinstance(resolved, dict):
        raise HostBoundaryError(f"observation schema definition {name} must be an object")
    return resolved


def _schema_errors(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    at: str = "$",
) -> list[str]:
    schema = _resolve_schema_ref(schema, root)
    errors: list[str] = []
    if branches := schema.get("oneOf"):
        matches = [not _schema_errors(value, branch, root, at) for branch in branches]
        if matches.count(True) != 1:
            return [f"{at}: expected exactly one allowed shape"]
        return []

    expected = schema.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, choice) for choice in choices):
            return [f"{at}: expected {' or '.join(choices)}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{at}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{at}: expected one of {schema['enum']!r}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{at}: string is too short")
        if pattern := schema.get("pattern"):
            if re.fullmatch(pattern, value) is None:
                errors.append(f"{at}: does not match {pattern!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{at}: expected ISO 8601 date-time")
            else:
                if parsed.utcoffset() is None:
                    errors.append(f"{at}: date-time must include a UTC offset")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{at}: must be at least {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{at}: expected at least {schema['minItems']} item(s)")
        if item_schema := schema.get("items"):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, root, f"{at}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{at}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value.keys() - properties.keys():
                errors.append(f"{at}.{key}: unknown property")
        for key, child in value.items():
            if key in properties:
                errors.extend(_schema_errors(child, properties[key], root, f"{at}.{key}"))
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
    except OSError as error:
        raise HostBoundaryError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _resolve_within(root: Path, relative: str, label: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise HostBoundaryError(f"{label} escapes installed skill root") from error
    if not candidate.is_file():
        raise HostBoundaryError(f"{label} missing: {candidate}")
    return candidate


def load_descriptor(path: Path = DEFAULT_DESCRIPTOR) -> dict[str, Any]:
    """Load and validate the repository-owned host descriptor."""
    descriptor = _read_object(path, "host capability descriptor")
    _require_exact_keys(descriptor, EXPECTED_DESCRIPTOR_KEYS, "host capability descriptor")
    if descriptor["schema"] != "atelier.host-capability/v1":
        raise HostBoundaryError("unsupported host capability descriptor schema")
    if descriptor["reference_host"] != "codex":
        raise HostBoundaryError("reference host must be codex")
    if (
        descriptor["delegated_capability"]
        != "agent-scripts.implement-ticket/delegated-execution/v1"
    ):
        raise HostBoundaryError("delegated capability identifier is incompatible")
    if descriptor["native_state_access"] != "read-only":
        raise HostBoundaryError("native state access must be read-only")
    if descriptor["fallback_to_copied_workflows"] is not False:
        raise HostBoundaryError("copied workflow fallback must be disabled")

    delegated = descriptor["delegated_skill"]
    native_state = descriptor["native_state"]
    if not isinstance(delegated, dict) or not isinstance(native_state, dict):
        raise HostBoundaryError("delegated_skill and native_state must be objects")
    _require_exact_keys(delegated, EXPECTED_DELEGATED_KEYS, "delegated_skill")
    _require_exact_keys(native_state, EXPECTED_NATIVE_STATE_KEYS, "native_state")
    if native_state["access"] != "read-only":
        raise HostBoundaryError("native_state.access must be read-only")
    operations = native_state["required_operations"]
    if (
        not isinstance(operations, list)
        or not operations
        or any(not isinstance(item, str) or not item for item in operations)
        or len(operations) != len(set(operations))
    ):
        raise HostBoundaryError("native_state.required_operations must be unique strings")
    for field in ("delegated_authority_actions", "accepted_terminal_states"):
        values = descriptor[field]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) or not item for item in values)
            or len(values) != len(set(values))
        ):
            raise HostBoundaryError(f"{field} must be unique strings")
    return descriptor


def check_host(
    *,
    descriptor_path: Path,
    skill_name: str,
    skill_root: Path,
    connector: str,
    operations: list[str],
) -> dict[str, Any]:
    """Prove exact dependency identity and required read-only host operations."""
    descriptor = load_descriptor(descriptor_path)
    delegated = descriptor["delegated_skill"]
    native_state = descriptor["native_state"]
    if skill_name != delegated["stable_name"]:
        raise HostBoundaryError(
            f"installed skill name mismatch: expected {delegated['stable_name']}"
        )
    if connector != native_state["connector"]:
        raise HostBoundaryError(
            f"connector identity mismatch: expected {native_state['connector']}"
        )
    missing_operations = sorted(set(native_state["required_operations"]) - set(operations))
    if missing_operations:
        raise HostBoundaryError(
            "missing read-only host operations: " + ", ".join(missing_operations)
        )

    resolved_root = skill_root.resolve()
    skill_file = _resolve_within(resolved_root, "SKILL.md", "installed skill")
    if _sha256(skill_file) != delegated["skill_sha256"]:
        raise HostBoundaryError("installed skill hash mismatch")
    first_lines = skill_file.read_text(encoding="utf-8").splitlines()[:4]
    if f"name: {delegated['frontmatter_name']}" not in first_lines:
        raise HostBoundaryError("installed skill frontmatter identity mismatch")

    manifest_path = _resolve_within(
        resolved_root,
        delegated["capability_manifest"],
        "delegated capability manifest",
    )
    if _sha256(manifest_path) != delegated["capability_manifest_sha256"]:
        raise HostBoundaryError("delegated capability manifest hash mismatch")
    manifest = _read_object(manifest_path, "delegated capability manifest")
    if manifest.get("id") != descriptor["delegated_capability"]:
        raise HostBoundaryError("delegated capability manifest identifier mismatch")

    capability_root = manifest_path.parent
    referenced: dict[str, Path] = {}
    for field in CAPABILITY_FILE_FIELDS:
        relative = manifest.get(field)
        if not isinstance(relative, str) or not relative:
            raise HostBoundaryError(f"delegated capability manifest missing {field}")
        referenced[field] = _resolve_within(
            capability_root,
            relative,
            f"delegated capability {field}",
        )
    for field in (
        "invocation_schema",
        "checkpoint_request_schema",
        "checkpoint_response_schema",
        "result_schema",
    ):
        _read_object(referenced[field], f"delegated capability {field}")
    invocation_schema = _read_object(
        referenced["invocation_schema"],
        "delegated capability invocation_schema",
    )
    try:
        supported_actions = set(invocation_schema["$defs"]["action"]["enum"])
    except (KeyError, TypeError) as error:
        raise HostBoundaryError(
            "delegated invocation schema does not expose authority actions"
        ) from error
    missing_actions = sorted(set(descriptor["delegated_authority_actions"]) - supported_actions)
    if missing_actions:
        raise HostBoundaryError(
            "delegated invocation schema lacks authority actions: " + ", ".join(missing_actions)
        )
    terminal_states = manifest.get("terminal_states")
    if not isinstance(terminal_states, list):
        raise HostBoundaryError("delegated capability manifest missing terminal_states")
    missing_terminals = sorted(set(descriptor["accepted_terminal_states"]) - set(terminal_states))
    if missing_terminals:
        raise HostBoundaryError(
            "delegated capability manifest lacks terminal states: " + ", ".join(missing_terminals)
        )

    completed = subprocess.run(
        [sys.executable, str(referenced["validator"]), "capability", str(manifest_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise HostBoundaryError(f"dependency-owned capability validation failed: {detail}")

    schema_path = _resolve_within(
        descriptor_path.parent,
        native_state["observation_schema"],
        "native-state observation schema",
    )
    _read_object(schema_path, "native-state observation schema")
    return {
        "schema": "atelier.host-check/v1",
        "status": "compatible",
        "reference_host": "codex",
        "delegated_skill": skill_name,
        "delegated_capability": descriptor["delegated_capability"],
        "delegated_authority_actions": descriptor["delegated_authority_actions"],
        "accepted_terminal_states": descriptor["accepted_terminal_states"],
        "connector": connector,
        "native_state_access": "read-only",
        "operations": sorted(set(native_state["required_operations"])),
    }


def _require_unique_ids(items: list[dict[str, Any]], label: str) -> None:
    ids = [item["id"] for item in items]
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        raise HostBoundaryError(f"{label} contains duplicate ids: {', '.join(duplicates)}")


def validate_observation(
    path: Path,
    schema_path: Path = ROOT / "references" / "github-observation.schema.json",
) -> dict[str, Any]:
    """Validate one complete, normalized, read-only GitHub observation."""
    value = _read_object(path, "native-state observation")
    schema = _read_object(schema_path, "native-state observation schema")
    errors = _schema_errors(value, schema, schema)
    if errors:
        detail = "; ".join(errors[:5])
        if len(errors) > 5:
            detail += f"; and {len(errors) - 5} more"
        raise HostBoundaryError(detail)

    repository = value["repository"]["name_with_owner"]
    issue = value["issue"]
    pull_request = value["pull_request"]
    pr_number = pull_request["number"] if pull_request else None
    candidate_sha = pull_request["head"]["sha"] if pull_request else None
    if pull_request is None and any(
        value[name] for name in ("pull_request_comments", "reviews", "checks", "threads")
    ):
        raise HostBoundaryError("pull-request collections require pull_request identity")
    if pull_request is not None:
        if pull_request["base"]["repository"] != repository:
            raise HostBoundaryError("pull_request.base repository identity mismatch")
        if pull_request["merged"] != (pull_request["state"] == "MERGED"):
            raise HostBoundaryError("pull_request merged state is inconsistent")
    for collection in ("issue_comments", "pull_request_comments", "reviews", "checks", "threads"):
        _require_unique_ids(value[collection], collection)
    for collection in ("sub_issues", "blocked_by", "blocking"):
        ids = [item["id"] for item in issue[collection]]
        if ids != sorted(set(ids)):
            raise HostBoundaryError(f"issue.{collection} must be unique and sorted by id")
    for collection in ("reviews", "checks", "threads"):
        for index, item in enumerate(value[collection]):
            if item["pull_request_number"] != pr_number:
                raise HostBoundaryError(f"{collection}[{index}] pull request identity mismatch")
    for index, check in enumerate(value["checks"]):
        if check["candidate_sha"] != candidate_sha:
            raise HostBoundaryError(f"checks[{index}] candidate SHA mismatch")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--descriptor",
        type=Path,
        default=DEFAULT_DESCRIPTOR,
        help="Repository-owned host capability descriptor",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="Validate installed host dependencies")
    check.add_argument("--skill-name", required=True)
    check.add_argument("--skill-root", required=True, type=Path)
    check.add_argument("--connector", required=True)
    check.add_argument("--operation", action="append", default=[])
    observation = subparsers.add_parser(
        "validate-observation",
        help="Validate one normalized GitHub observation",
    )
    observation.add_argument("path", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "check":
            result = check_host(
                descriptor_path=args.descriptor,
                skill_name=args.skill_name,
                skill_root=args.skill_root,
                connector=args.connector,
                operations=args.operation,
            )
        else:
            observation = validate_observation(args.path)
            pull_request = observation["pull_request"]
            result = {
                "schema": "atelier.observation-check/v1",
                "status": "valid",
                "repository": observation["repository"]["name_with_owner"],
                "issue": observation["issue"]["number"],
                "pull_request": pull_request["number"] if pull_request else None,
                "candidate_sha": pull_request["head"]["sha"] if pull_request else None,
            }
    except HostBoundaryError as error:
        print(f"ERROR host-boundary: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

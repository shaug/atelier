#!/usr/bin/env python3
"""Validate v1 Atelier documents and reconstruct transient mailbox state."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only on an incomplete host
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "references" / "mailbox-v1.schema.json"

DOCUMENT_SCHEMAS = {
    "atelier.mailbox/v1": "mailbox",
    "atelier.project/v1": "project",
    "atelier.initiative/v1": "initiative",
    "atelier.work/v1": "work",
    "atelier.message/v1": "message",
    "atelier.receipt/v1": "receipt",
    "atelier.project-policy/v1": "project_policy",
}
WORK_STATES = {
    "draft",
    "approved",
    "active",
    "blocked",
    "delivered",
    "accepted",
    "deferred",
    "cancelled",
}
ACTIVE_STATES = {"active", "blocked", "delivered"}
CANDIDATE_REQUIRED_ACTIONS = {
    "repository.candidate.push",
    "pull_request.create",
    "pull_request.update",
    "review.reply",
    "review.resolve",
}


@dataclass(frozen=True)
class Diagnostic:
    """One deterministic validation or reconstruction diagnostic."""

    path: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


class MailboxValidationError(ValueError):
    """Mailbox state cannot be interpreted without guessing."""

    def __init__(self, diagnostics: list[Diagnostic]):
        ordered = sorted(diagnostics, key=lambda item: (item.path, item.code, item.message))
        self.diagnostics = ordered
        super().__init__("; ".join(item.render() for item in ordered[:5]))


def _fail(path: str, code: str, message: str) -> MailboxValidationError:
    return MailboxValidationError([Diagnostic(path, code, message)])


class _YamlDuplicateKey(ValueError):
    pass


class _YamlNonStringKey(ValueError):
    pass


if yaml is not None:

    class _StrictSafeLoader(yaml.SafeLoader):
        """Safe YAML loader with JSON-shaped, YAML 1.2 scalar semantics."""

    _StrictSafeLoader.yaml_implicit_resolvers = {
        character: list(resolvers)
        for character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    for character, resolvers in _StrictSafeLoader.yaml_implicit_resolvers.items():
        _StrictSafeLoader.yaml_implicit_resolvers[character] = [
            resolver
            for resolver in resolvers
            if resolver[0]
            not in {
                "tag:yaml.org,2002:bool",
                "tag:yaml.org,2002:int",
                "tag:yaml.org,2002:timestamp",
            }
        ]
    _StrictSafeLoader.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:true|false)$"),
        list("tf"),
    )
    _StrictSafeLoader.add_implicit_resolver(
        "tag:yaml.org,2002:int",
        re.compile(r"^-?(?:0|[1-9][0-9]*)$"),
        list("-0123456789"),
    )

    def _construct_mapping(
        loader: Any, node: Any, *, deep: bool = False
    ) -> dict[str, Any]:
        loader.flatten_mapping(node)
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise _YamlNonStringKey(f"line {key_node.start_mark.line + 1}")
            if key in mapping:
                raise _YamlDuplicateKey(
                    f"line {key_node.start_mark.line + 1} repeats {key!r}"
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_mapping,
    )


def _parse_yaml(text: str, path: str) -> dict[str, Any]:
    if yaml is None:
        raise _fail(path, "yaml-dependency", "safe YAML support is unavailable")
    try:
        parsed = yaml.load(text, Loader=_StrictSafeLoader)
    except _YamlDuplicateKey as error:
        raise _fail(path, "yaml-duplicate-key", str(error)) from error
    except _YamlNonStringKey as error:
        raise _fail(path, "yaml-key", f"{error} has a non-string mapping key") from error
    except yaml.YAMLError as error:
        detail = getattr(error, "problem", None) or "document is not valid YAML"
        raise _fail(path, "yaml-syntax", detail) from error
    if parsed is None:
        raise _fail(path, "yaml-empty", "document is empty")
    if not isinstance(parsed, dict):
        raise _fail(path, "yaml-root", "document root must be a mapping")

    active_collections: set[int] = set()

    def validate_json_shape(value: Any, at: str = "$") -> None:
        if value is None or isinstance(value, str | bool | int):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise _fail(path, "yaml-value", f"{at} contains a non-finite number")
            return
        if not isinstance(value, dict | list):
            raise _fail(
                path,
                "yaml-value",
                f"{at} has unsupported YAML type {type(value).__name__}",
            )
        identity = id(value)
        if identity in active_collections:
            raise _fail(path, "yaml-recursion", "document contains a recursive alias")
        active_collections.add(identity)
        if isinstance(value, dict):
            for key, child in value.items():
                validate_json_shape(child, f"{at}.{key}")
        else:
            for index, child in enumerate(value):
                validate_json_shape(child, f"{at}[{index}]")
        active_collections.remove(identity)

    validate_json_shape(parsed)
    return parsed


def _read_yaml(
    path: Path, *, frontmatter: bool, label: str | None = None
) -> tuple[dict[str, Any], str]:
    label = label or path.as_posix()
    if path.is_symlink():
        raise _fail(label, "symlink", "normative documents must not be symbolic links")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise _fail(label, "encoding", "document is not valid UTF-8") from error
    except OSError as error:
        raise _fail(label, "unreadable", "document could not be read") from error
    if not frontmatter:
        return _parse_yaml(text, label), ""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise _fail(label, "frontmatter", "Markdown document must begin with '---'")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise _fail(label, "frontmatter", "Markdown frontmatter is not terminated") from error
    return _parse_yaml("\n".join(lines[1:end]), label), "\n".join(lines[end + 1 :])


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _fail(path.as_posix(), "schema-unreadable", str(error)) from error
    if not isinstance(value, dict) or not isinstance(value.get("$defs"), dict):
        raise _fail(path.as_posix(), "schema-invalid", "schema bundle must define $defs")
    return value


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any], label: str) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    prefix = "#/$defs/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise _fail(label, "schema-ref", f"unsupported schema reference {reference!r}")
    try:
        resolved = root["$defs"][reference.removeprefix(prefix)]
    except KeyError as error:
        raise _fail(label, "schema-ref", f"missing schema definition {reference!r}") from error
    if not isinstance(resolved, dict):
        raise _fail(label, "schema-ref", f"schema definition {reference!r} is not an object")
    return resolved


def _schema_diagnostics(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    *,
    document: str,
    at: str = "$",
) -> list[Diagnostic]:
    schema = _resolve_ref(schema, root, document)
    if branches := schema.get("oneOf"):
        branch_errors = [
            _schema_diagnostics(value, branch, root, document=document, at=at)
            for branch in branches
        ]
        if sum(not errors for errors in branch_errors) != 1:
            return [
                Diagnostic(
                    document,
                    "schema-one-of",
                    f"{at} does not match exactly one allowed shape",
                )
            ]
        return []

    diagnostics: list[Diagnostic] = []
    expected = schema.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, choice) for choice in choices):
            return [
                Diagnostic(
                    document,
                    "schema-type",
                    f"{at} expected {' or '.join(choices)}",
                )
            ]
    if "const" in schema and not _json_equal(value, schema["const"]):
        diagnostics.append(
            Diagnostic(document, "schema-const", f"{at} expected {schema['const']!r}")
        )
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        diagnostics.append(
            Diagnostic(document, "schema-enum", f"{at} has unsupported value {value!r}")
        )
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            diagnostics.append(Diagnostic(document, "schema-length", f"{at} is too short"))
        if pattern := schema.get("pattern"):
            if re.fullmatch(pattern, value) is None:
                diagnostics.append(
                    Diagnostic(document, "schema-pattern", f"{at} is malformed")
                )
        if schema.get("format") == "date-time":
            if re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                value,
            ) is None:
                parsed = None
            else:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    parsed = None
            if parsed is None or parsed.utcoffset() is None:
                diagnostics.append(
                    Diagnostic(
                        document,
                        "schema-date-time",
                        f"{at} must be an RFC 3339 timestamp with a UTC offset",
                    )
                )
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            diagnostics.append(
                Diagnostic(
                    document,
                    "schema-minimum",
                    f"{at} must be at least {schema['minimum']}",
                )
            )
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            diagnostics.append(
                Diagnostic(document, "schema-items", f"{at} has too few items")
            )
        normalized_items = {json.dumps(item, sort_keys=True) for item in value}
        if schema.get("uniqueItems") and len(normalized_items) != len(value):
            diagnostics.append(
                Diagnostic(document, "schema-unique", f"{at} contains duplicates")
            )
        if item_schema := schema.get("items"):
            for index, item in enumerate(value):
                diagnostics.extend(
                    _schema_diagnostics(
                        item,
                        item_schema,
                        root,
                        document=document,
                        at=f"{at}[{index}]",
                    )
                )
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if len(value) < schema.get("minProperties", 0):
            diagnostics.append(
                Diagnostic(document, "schema-properties", f"{at} has too few fields")
            )
        for key in schema.get("required", []):
            if key not in value:
                diagnostics.append(
                    Diagnostic(
                        document,
                        "schema-required",
                        f"{at} is missing required field {key!r}",
                    )
                )
        if schema.get("additionalProperties") is False:
            for key in sorted(value.keys() - properties.keys()):
                diagnostics.append(
                    Diagnostic(document, "schema-unknown", f"{at}.{key} is unknown")
                )
        for key, child in value.items():
            if key in properties:
                diagnostics.extend(
                    _schema_diagnostics(
                        child,
                        properties[key],
                        root,
                        document=document,
                        at=f"{at}.{key}",
                    )
                )
    return diagnostics


def validate_document(
    value: dict[str, Any],
    *,
    path: str,
    schema_bundle: dict[str, Any],
    expected_schema: str | None = None,
) -> None:
    """Validate one structured document against its exact frozen v1 schema."""
    schema_name = value.get("schema")
    if not isinstance(schema_name, str) or schema_name not in DOCUMENT_SCHEMAS:
        raise _fail(path, "unsupported-schema", f"unsupported schema {schema_name!r}")
    if expected_schema is not None and schema_name != expected_schema:
        raise _fail(path, "wrong-schema", f"expected {expected_schema}, found {schema_name}")
    definition = schema_bundle["$defs"].get(DOCUMENT_SCHEMAS[schema_name])
    if not isinstance(definition, dict):
        raise _fail(path, "schema-missing", f"schema definition for {schema_name} is absent")
    diagnostics = _schema_diagnostics(
        value, definition, schema_bundle, document=path
    )
    if diagnostics:
        raise MailboxValidationError(diagnostics)


def validate_project_policy(path: Path) -> dict[str, Any]:
    """Validate one managed-project policy without changing it."""
    value, _ = _read_yaml(path, frontmatter=False)
    validate_document(
        value,
        path=path.as_posix(),
        schema_bundle=_load_schema(DEFAULT_SCHEMA),
        expected_schema="atelier.project-policy/v1",
    )
    if not _valid_branch_ref(value["repository"]["canonical_ref"]):
        raise _fail(
            path.as_posix(),
            "git-ref",
            "repository canonical_ref is not a valid full Git branch ref",
        )
    if not _valid_branch_name(value["mailbox"]["canonical_branch"]):
        raise _fail(
            path.as_posix(),
            "git-ref",
            "mailbox canonical_branch is not a valid Git branch name",
        )
    if _remote_has_embedded_credentials(value["mailbox"]["remote"]):
        raise _fail(
            path.as_posix(),
            "remote-credentials",
            "mailbox remote must not contain embedded credentials",
        )
    if not _valid_repository_identity(value["repository"]["identity"]):
        raise _fail(
            path.as_posix(),
            "repository-identity",
            "repository identity is not a canonical GitHub owner/repository pair",
        )
    return value


def _valid_branch_ref(value: str) -> bool:
    if not value.startswith("refs/heads/") or value.endswith(("/", ".")):
        return False
    if ".." in value or "@{" in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    if any(character in " ~^:?*[\\\\" for character in value):
        return False
    components = value.split("/")
    return all(
        component
        and not component.startswith(".")
        and not component.endswith(".lock")
        for component in components
    )


def _valid_branch_name(value: str) -> bool:
    return not value.startswith("-") and _valid_branch_ref(f"refs/heads/{value}")


def _remote_has_embedded_credentials(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.query or parsed.fragment) or parsed.password is not None or (
        parsed.scheme.lower() in {"http", "https"} and parsed.username is not None
    )


def _valid_repository_identity(repository: str) -> bool:
    if not repository.startswith("github:"):
        return False
    parts = repository.removeprefix("github:").split("/")
    return len(parts) == 2 and all(part not in {"", ".", ".."} for part in parts)


def _github_object_url(
    url: str,
    *,
    repository: str,
    object_kind: str,
    object_id: str | None = None,
) -> bool:
    if not _valid_repository_identity(repository):
        return False
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        return False
    repository_parts = repository.removeprefix("github:").split("/")
    path_parts = parsed.path.strip("/").split("/")
    if (
        len(repository_parts) != 2
        or len(path_parts) != 4
        or [part.lower() for part in path_parts[:2]]
        != [part.lower() for part in repository_parts]
        or path_parts[2] != object_kind
        or not path_parts[3].isdigit()
    ):
        return False
    return object_id is None or path_parts[3] == object_id


def _github_remote_url(url: str, *, repository: str) -> bool:
    if not _valid_repository_identity(repository):
        return False
    expected = repository.removeprefix("github:").removesuffix(".git").lower()
    scp_match = re.fullmatch(r"git@github\.com:(.+)", url, flags=re.IGNORECASE)
    if scp_match is not None:
        actual = scp_match.group(1).removesuffix(".git").lower()
        return actual == expected
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.hostname != "github.com":
        return False
    if parsed.scheme == "ssh":
        if parsed.username != "git" or parsed.password is not None:
            return False
    elif parsed.scheme == "https":
        if parsed.username is not None or parsed.password is not None:
            return False
    else:
        return False
    actual = parsed.path.strip("/").removesuffix(".git").lower()
    return actual == expected


def _repository_identity_key(repository: str) -> str:
    return repository.lower() if repository.startswith("github:") else repository


def _candidate_reference_diagnostics(
    path: str, candidate: dict[str, Any] | None
) -> list[Diagnostic]:
    if candidate is None:
        return []
    diagnostics: list[Diagnostic] = []
    if not _valid_repository_identity(candidate["repository"]):
        diagnostics.append(
            Diagnostic(
                path,
                "repository-identity",
                "candidate repository is not a canonical GitHub owner/repository pair",
            )
        )
    if not _valid_branch_ref(candidate["remote_ref"]):
        diagnostics.append(
            Diagnostic(path, "git-ref", "candidate remote_ref is not a valid full Git branch ref")
        )
    if not _github_remote_url(candidate["remote_url"], repository=candidate["repository"]):
        diagnostics.append(
            Diagnostic(
                path,
                "candidate-remote-url",
                "candidate remote URL contradicts its repository",
            )
        )
    workspace_id = candidate["workspace_id"]
    if workspace_id is not None and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}", workspace_id
    ) is None:
        diagnostics.append(
            Diagnostic(
                path,
                "workspace-id",
                "candidate workspace_id must be an opaque durable host identifier",
            )
        )
    pull_request = candidate["pull_request"]
    if pull_request is not None and not _github_object_url(
        pull_request,
        repository=candidate["repository"],
        object_kind="pull",
    ):
        diagnostics.append(
            Diagnostic(
                path,
                "candidate-pull-request",
                "candidate pull-request URL contradicts its repository",
            )
        )
    return diagnostics


def _expected_child_directories(root: Path, name: str) -> list[Path]:
    directory = root / name
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise _fail(name, "layout", "expected a directory")
    return sorted((entry for entry in directory.iterdir() if entry.is_dir()), key=lambda p: p.name)


def _require_no_unexpected_entries(root: Path) -> None:
    diagnostics: list[Diagnostic] = []
    for group, document_name, allowed_children in (
        ("projects", "project.md", set()),
        ("initiatives", "initiative.md", set()),
        ("work", "work.md", {"messages", "receipts"}),
    ):
        directory = root / group
        if not directory.exists():
            continue
        if directory.is_symlink():
            diagnostics.append(
                Diagnostic(group, "symlink", "mailbox directories must not be symbolic links")
            )
            continue
        if not directory.is_dir():
            diagnostics.append(
                Diagnostic(group, "layout", "mailbox collection must be a directory")
            )
            continue
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                diagnostics.append(
                    Diagnostic(
                        entry.relative_to(root).as_posix(),
                        "symlink",
                        "mailbox entries must not be symbolic links",
                    )
                )
                continue
            if not entry.is_dir():
                diagnostics.append(
                    Diagnostic(entry.relative_to(root).as_posix(), "layout", "unexpected file")
                )
                continue
            expected = entry / document_name
            if not expected.is_file():
                diagnostics.append(
                    Diagnostic(
                        expected.relative_to(root).as_posix(),
                        "layout",
                        "required document is missing",
                    )
                )
            for child in sorted(entry.iterdir(), key=lambda item: item.name):
                if child.is_symlink():
                    diagnostics.append(
                        Diagnostic(
                            child.relative_to(root).as_posix(),
                            "symlink",
                            "mailbox entries must not be symbolic links",
                        )
                    )
                    continue
                if child.name == document_name:
                    continue
                if child.name not in allowed_children or not child.is_dir():
                    diagnostics.append(
                        Diagnostic(
                            child.relative_to(root).as_posix(),
                            "layout",
                            "unexpected mailbox entry",
                        )
                    )
                    continue
                for nested in sorted(child.iterdir(), key=lambda item: item.name):
                    if nested.is_symlink() or not nested.is_file() or nested.suffix != ".md":
                        diagnostics.append(
                            Diagnostic(
                                nested.relative_to(root).as_posix(),
                                "layout",
                                "expected a Markdown document",
                            )
                        )
    if diagnostics:
        raise MailboxValidationError(diagnostics)


def _load_documents(
    root: Path, schema_bundle: dict[str, Any]
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, dict[str, Any]]],
    dict[str, dict[str, dict[str, Any]]],
]:
    manifest_path = root / "atelier.yaml"
    manifest, _ = _read_yaml(manifest_path, frontmatter=False, label="atelier.yaml")
    validate_document(
        manifest,
        path="atelier.yaml",
        schema_bundle=schema_bundle,
        expected_schema="atelier.mailbox/v1",
    )
    _require_no_unexpected_entries(root)

    projects: dict[str, dict[str, Any]] = {}
    initiatives: dict[str, dict[str, Any]] = {}
    works: dict[str, dict[str, Any]] = {}
    messages: dict[str, dict[str, dict[str, Any]]] = {}
    receipts: dict[str, dict[str, dict[str, Any]]] = {}

    for directory in _expected_child_directories(root, "projects"):
        relative = f"projects/{directory.name}/project.md"
        value, _ = _read_yaml(root / relative, frontmatter=True, label=relative)
        validate_document(
            value,
            path=relative,
            schema_bundle=schema_bundle,
            expected_schema="atelier.project/v1",
        )
        if value["id"] != directory.name:
            raise _fail(relative, "path-identity", "project id does not match its directory")
        if value["id"] in projects:
            raise _fail(relative, "duplicate-identity", "project id is duplicated")
        projects[value["id"]] = value

    for directory in _expected_child_directories(root, "initiatives"):
        relative = f"initiatives/{directory.name}/initiative.md"
        value, _ = _read_yaml(root / relative, frontmatter=True, label=relative)
        validate_document(
            value,
            path=relative,
            schema_bundle=schema_bundle,
            expected_schema="atelier.initiative/v1",
        )
        if value["id"] != directory.name:
            raise _fail(relative, "path-identity", "initiative id does not match its directory")
        if value["id"] in initiatives:
            raise _fail(relative, "duplicate-identity", "initiative id is duplicated")
        initiatives[value["id"]] = value

    for directory in _expected_child_directories(root, "work"):
        relative = f"work/{directory.name}/work.md"
        value, _ = _read_yaml(root / relative, frontmatter=True, label=relative)
        validate_document(
            value,
            path=relative,
            schema_bundle=schema_bundle,
            expected_schema="atelier.work/v1",
        )
        if value["id"] != directory.name:
            raise _fail(relative, "path-identity", "work id does not match its directory")
        if value["id"] in works:
            raise _fail(relative, "duplicate-identity", "work id is duplicated")
        works[value["id"]] = value
        messages[value["id"]] = {}
        receipts[value["id"]] = {}
        for child_name, expected, target in (
            ("messages", "atelier.message/v1", messages[value["id"]]),
            ("receipts", "atelier.receipt/v1", receipts[value["id"]]),
        ):
            child_root = directory / child_name
            if not child_root.exists():
                continue
            for path in sorted(child_root.glob("*.md")):
                child_relative = path.relative_to(root).as_posix()
                child, _ = _read_yaml(path, frontmatter=True, label=child_relative)
                validate_document(
                    child,
                    path=child_relative,
                    schema_bundle=schema_bundle,
                    expected_schema=expected,
                )
                if child["id"] != path.stem:
                    raise _fail(
                        child_relative,
                        "path-identity",
                        f"{child_name[:-1]} id does not match its filename",
                    )
                if child["work_id"] != value["id"]:
                    raise _fail(
                        child_relative,
                        "work-identity",
                        f"{child_name[:-1]} belongs to another work item",
                    )
                if child["id"] in target:
                    raise _fail(
                        child_relative,
                        "duplicate-identity",
                        f"{child_name[:-1]} id is duplicated",
                    )
                target[child["id"]] = child
    return manifest, projects, initiatives, works, messages, receipts


def _check_dependency_cycles(works: dict[str, dict[str, Any]]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(work_id: str) -> None:
        if work_id in visited:
            return
        if work_id in visiting:
            cycle = visiting[visiting.index(work_id) :] + [work_id]
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/work.md",
                    "dependency-cycle",
                    " -> ".join(cycle),
                )
            )
            return
        visiting.append(work_id)
        for dependency in works[work_id]["dependencies"]:
            if dependency in works:
                visit(dependency)
        visiting.pop()
        visited.add(work_id)

    for work_id in sorted(works):
        visit(work_id)
    return diagnostics


def _check_replacement_cycles(works: dict[str, dict[str, Any]]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(work_id: str) -> None:
        if work_id in visited:
            return
        if work_id in visiting:
            cycle = visiting[visiting.index(work_id) :] + [work_id]
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/work.md",
                    "replacement-cycle",
                    " -> ".join(cycle),
                )
            )
            return
        visiting.append(work_id)
        for replaced in works[work_id]["replaces"]:
            if replaced in works:
                visit(replaced)
        visiting.pop()
        visited.add(work_id)

    for work_id in sorted(works):
        visit(work_id)
    return diagnostics


def _message_reference_cycle(
    work_messages: dict[str, dict[str, Any]],
) -> str | None:
    state: dict[str, int] = {}

    def visit(message_id: str) -> str | None:
        state[message_id] = 1
        message = work_messages[message_id]
        references = sorted(
            reference
            for reference in (message["in_reply_to"], message["resolves"])
            if reference in work_messages
        )
        for reference in references:
            if state.get(reference) == 1:
                return message_id
            if state.get(reference, 0) == 0:
                cycle = visit(reference)
                if cycle is not None:
                    return cycle
        state[message_id] = 2
        return None

    for message_id in sorted(work_messages):
        if state.get(message_id, 0) == 0:
            cycle = visit(message_id)
            if cycle is not None:
                return cycle
    return None


def _validate_claim(
    work_id: str,
    work: dict[str, Any],
    attempt_receipt: dict[str, Any] | None,
) -> list[Diagnostic]:
    claim = work["claim"]
    if claim is None:
        return []
    path = f"work/{work_id}/work.md"
    diagnostics: list[Diagnostic] = []
    approval = work["approval"]
    if approval is None or claim["work_revision"] != work["revision"]:
        diagnostics.append(
            Diagnostic(path, "claim-revision", "claim does not name the approved work revision")
        )
    elif approval["revision"] != work["revision"]:
        diagnostics.append(
            Diagnostic(path, "approval-revision", "approval does not name the current revision")
        )
    ledger = claim["checkpoint"]["authorizations"]
    sequences = [entry["sequence"] for entry in ledger]
    expected = list(range(1, claim["checkpoint"]["sequence"] + 1))
    if sequences != expected:
        diagnostics.append(
            Diagnostic(path, "checkpoint-sequence", "authorization ledger is not contiguous")
        )
    if any(entry["invocation_id"] != claim["worker_run_id"] for entry in ledger):
        diagnostics.append(
            Diagnostic(path, "checkpoint-invocation", "authorization names another worker run")
        )
    authority_ceiling = set(approval["authority_ceiling"]) if approval is not None else set()
    transferable_handoff = (
        attempt_receipt is not None
        and attempt_receipt["handoff"] == "transferable"
        and attempt_receipt["claim_id"] != claim["id"]
    )
    latest_acknowledged_head = (
        attempt_receipt["candidate"]["head_revision"]
        if transferable_handoff and attempt_receipt["candidate"] is not None
        else None
    )
    previous_entry: dict[str, Any] | None = None
    for entry in ledger:
        action = entry["action"]
        phase = entry["phase"]
        candidate_head = entry["candidate_head"]
        acknowledged_head = entry["acknowledged_candidate_head"]
        if action not in authority_ceiling:
            diagnostics.append(
                Diagnostic(
                    path,
                    "checkpoint-authority",
                    f"authorization action {action!r} exceeds the approved authority ceiling",
                )
            )
        if phase == "candidate_published":
            paired_push = (
                previous_entry is not None
                and previous_entry["phase"] == "pre_external_mutation"
                and previous_entry["action"] == "repository.candidate.push"
                and previous_entry["candidate_head"] == candidate_head
            )
            if not paired_push:
                diagnostics.append(
                    Diagnostic(
                        path,
                        "checkpoint-candidate-history",
                        "candidate publication must immediately follow "
                        "its exact push authorization",
                    )
                )
            if (
                action != "repository.candidate.push"
                or candidate_head is None
                or acknowledged_head != candidate_head
            ):
                diagnostics.append(
                    Diagnostic(
                        path,
                        "checkpoint-phase",
                        "candidate_published must acknowledge an exact repository candidate push",
                    )
                )
            elif paired_push:
                latest_acknowledged_head = candidate_head
        else:
            if acknowledged_head is not None:
                diagnostics.append(
                    Diagnostic(
                        path,
                        "checkpoint-acknowledgement",
                        "pre_external_mutation must not acknowledge a candidate",
                    )
                )
            if action in CANDIDATE_REQUIRED_ACTIONS and candidate_head is None:
                diagnostics.append(
                    Diagnostic(
                        path,
                        "checkpoint-candidate",
                        f"authorization action {action!r} requires an exact candidate head",
                    )
                )
            elif (
                action in CANDIDATE_REQUIRED_ACTIONS
                and action != "repository.candidate.push"
                and candidate_head != latest_acknowledged_head
            ):
                diagnostics.append(
                    Diagnostic(
                        path,
                        "checkpoint-candidate-history",
                        f"authorization action {action!r} does not name "
                        "the latest acknowledged candidate",
                    )
                )
        previous_entry = entry
    candidate = claim["candidate"]
    publication_entries = [entry for entry in ledger if entry["phase"] == "candidate_published"]
    internally_invalid = any(
        entry["candidate_head"] is None
        or entry["acknowledged_candidate_head"] != entry["candidate_head"]
        for entry in publication_entries
    )
    inherited_candidate = (
        candidate is not None
        and not publication_entries
        and transferable_handoff
        and attempt_receipt["candidate"] == candidate
    )
    current_unacknowledged = (
        candidate is not None
        and not inherited_candidate
        and (
            not publication_entries
            or publication_entries[-1]["candidate_head"] != candidate["head_revision"]
        )
    )
    discarded_handoff = transferable_handoff and (
        candidate is None or attempt_receipt["candidate"] != candidate
    )
    if (
        internally_invalid
        or current_unacknowledged
        or discarded_handoff
        or (candidate is None and publication_entries)
    ):
        diagnostics.append(
            Diagnostic(
                path,
                "candidate-acknowledgement",
                "candidate publication history does not acknowledge the current candidate",
            )
        )
    if (
        work["status"] == "delivered"
        and candidate is not None
        and candidate["pull_request"] is not None
        and not any(
            entry["phase"] == "pre_external_mutation"
            and entry["action"] in {"pull_request.create", "pull_request.update"}
            for entry in ledger
        )
    ):
        diagnostics.append(
            Diagnostic(
                path,
                "checkpoint-pr-authority",
                "delivered PR candidate lacks recorded pre-mutation authority",
            )
        )
    return diagnostics


def _validate_lifecycle(
    work_id: str,
    work: dict[str, Any],
    work_messages: dict[str, dict[str, Any]],
    work_receipts: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    path = f"work/{work_id}/work.md"
    approval = work["approval"]
    claim = work["claim"]
    blocker = work["blocking_message_id"]
    attempt = work["attempt_receipt_id"]
    attempt_receipt = work_receipts.get(attempt) if attempt is not None else None
    delivery = work["delivery_receipt_id"]
    acceptance = work["acceptance"]
    status = work["status"]
    diagnostics: list[Diagnostic] = []

    valid = {
        "draft": approval is None
        and claim is None
        and blocker is None
        and attempt is None
        and delivery is None
        and acceptance is None,
        "approved": approval is not None
        and claim is None
        and blocker is None
        and delivery is None
        and acceptance is None,
        "active": approval is not None
        and claim is not None
        and blocker is None
        and delivery is None
        and acceptance is None,
        "blocked": approval is not None
        and claim is not None
        and blocker is not None
        and attempt is not None
        and delivery is None
        and acceptance is None,
        "delivered": approval is not None
        and claim is not None
        and blocker is None
        and attempt is not None
        and attempt == delivery
        and acceptance is None,
        "accepted": approval is not None
        and claim is None
        and blocker is None
        and attempt is not None
        and attempt == delivery
        and acceptance is not None,
        "deferred": claim is None
        and blocker is None
        and delivery is None
        and acceptance is None,
        "cancelled": claim is None
        and blocker is None
        and delivery is None
        and acceptance is None,
    }
    if status not in WORK_STATES or not valid.get(status, False):
        diagnostics.append(
            Diagnostic(path, "lifecycle", f"{status!r} has contradictory lifecycle fields")
        )
        return diagnostics
    if status in {"active", "blocked", "delivered", "accepted"} and work["native_ticket"] is None:
        diagnostics.append(
            Diagnostic(path, "native-ticket", f"{status} work requires an eligible native ticket")
        )

    if approval is not None and approval["revision"] != work["revision"]:
        diagnostics.append(
            Diagnostic(path, "approval-revision", "approval does not name the current revision")
        )
    diagnostics.extend(_validate_claim(work_id, work, attempt_receipt))
    if claim is not None and any(
        receipt["outcome"] == "released"
        and (
            receipt["claim_id"] == claim["id"]
            or receipt["worker_run_id"] == claim["worker_run_id"]
        )
        for receipt in work_receipts.values()
    ):
        diagnostics.append(
            Diagnostic(
                path,
                "released-claim-identity",
                "current claim reuses an execution identity terminated by a release",
            )
        )

    resolutions: dict[str, list[str]] = {}
    for message_id, message in work_messages.items():
        if (message["author_role"] == "worker") != (message["worker_run_id"] is not None):
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/messages/{message_id}.md",
                    "message-author",
                    "worker_run_id must appear exactly for worker-authored messages",
                )
            )
        for reference_name in ("in_reply_to", "resolves"):
            reference = message[reference_name]
            if reference == message_id:
                diagnostics.append(
                    Diagnostic(
                        f"work/{work_id}/messages/{message_id}.md",
                        "message-self-reference",
                        f"{reference_name} cannot name the message itself",
                    )
                )
            if reference is not None and reference not in work_messages:
                diagnostics.append(
                    Diagnostic(
                        f"work/{work_id}/messages/{message_id}.md",
                        "message-reference",
                        f"{reference_name} names a missing message",
                    )
                )
        if message["resolves"] is not None:
            resolutions.setdefault(message["resolves"], []).append(message_id)
    cycle = _message_reference_cycle(work_messages)
    if cycle is not None:
        diagnostics.append(
            Diagnostic(
                f"work/{work_id}/messages/{cycle}.md",
                "message-cycle",
                "message references must form an acyclic history",
            )
        )
    for target, resolving in resolutions.items():
        if len(resolving) > 1:
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/messages/{target}.md",
                    "multiple-resolutions",
                    "message has more than one resolving message",
                )
            )
        target_message = work_messages.get(target)
        if (
            target_message is not None
            and target_message["blocks"] != "worker"
            and target_message["kind"] != "needs-decision"
        ):
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/messages/{target}.md",
                    "invalid-resolution",
                    "only a worker blocker or non-blocking decision can be resolved",
                )
            )
        for resolver_id in resolving:
            resolver = work_messages[resolver_id]
            if (
                resolver["author_role"] not in {"planner", "operator"}
                or resolver["worker_run_id"] is not None
            ):
                diagnostics.append(
                    Diagnostic(
                        f"work/{work_id}/messages/{resolver_id}.md",
                        "resolution-actor",
                        "decision resolutions require a planner or operator",
                    )
                )
    unresolved_worker_blockers = sorted(
        message_id
        for message_id, message in work_messages.items()
        if message["blocks"] == "worker" and message_id not in resolutions
    )
    expected_worker_blockers = [blocker] if blocker is not None else []
    if unresolved_worker_blockers != expected_worker_blockers:
        diagnostics.append(
            Diagnostic(
                path,
                "blocking-message",
                "unresolved worker blockers do not match the canonical blocker pointer",
            )
        )
    if blocker is not None:
        message = work_messages.get(blocker)
        if (
            message is None
            or message["kind"] not in {"needs-decision", "notification"}
            or message["blocks"] != "worker"
            or message["resolves"] is not None
            or blocker in resolutions
        ):
            diagnostics.append(
                Diagnostic(path, "blocking-message", "current blocker is missing or resolved")
            )
        if message is not None and (
            claim is None
            or message["author_role"] != "worker"
            or message["worker_run_id"] != claim["worker_run_id"]
        ):
            diagnostics.append(
                Diagnostic(
                    path,
                    "blocker-actor",
                    "current blocker must be authored by the claiming worker",
                )
            )

    if attempt is not None:
        if attempt_receipt is None:
            diagnostics.append(
                Diagnostic(path, "attempt-receipt", "attempt receipt does not exist")
            )
        elif approval is not None and attempt_receipt["approved_revision"] != approval["revision"]:
            diagnostics.append(
                Diagnostic(
                    path,
                    "attempt-revision",
                    "attempt receipt does not name the approved revision",
                )
            )
        if (
            status == "approved"
            and attempt_receipt is not None
            and attempt_receipt["outcome"] != "released"
        ):
            diagnostics.append(
                Diagnostic(
                    path,
                    "attempt-outcome",
                    "approved work may retain only its latest released attempt receipt",
                )
            )
        if (
            status == "blocked"
            and attempt_receipt is not None
            and (
                attempt_receipt["outcome"] != "blocked"
                or attempt_receipt["mutation_ownership"] != "retained"
            )
        ):
            diagnostics.append(
                Diagnostic(
                    path,
                    "attempt-outcome",
                    "blocked work requires a blocked attempt receipt with retained ownership",
                )
            )
        if claim is not None and status in {"blocked", "delivered"} and (
            attempt_receipt is None
            or attempt_receipt["claim_id"] != claim["id"]
            or attempt_receipt["worker_run_id"] != claim["worker_run_id"]
            or attempt_receipt["approved_commit"] != claim["approved_commit"]
            or attempt_receipt["policy_commit"] != claim["policy_commit"]
        ):
            diagnostics.append(
                Diagnostic(path, "attempt-identity", "attempt receipt contradicts the claim")
            )
    receipt = work_receipts.get(delivery) if delivery is not None else None
    if delivery is not None:
        if receipt is None or receipt["outcome"] != "delivered":
            diagnostics.append(
                Diagnostic(path, "delivery-receipt", "delivery does not name a delivered receipt")
            )
        elif claim is not None and (
            receipt["claim_id"] != claim["id"]
            or receipt["worker_run_id"] != claim["worker_run_id"]
            or receipt["candidate"] != claim["candidate"]
        ):
            diagnostics.append(
                Diagnostic(path, "delivery-identity", "delivery receipt contradicts the claim")
            )
    if acceptance is not None and receipt is not None:
        candidate = receipt["candidate"]
        if (
            acceptance["receipt_id"] != delivery
            or candidate is None
            or acceptance["candidate_revision"] != candidate["head_revision"]
        ):
            diagnostics.append(
                Diagnostic(path, "acceptance-identity", "acceptance contradicts the delivery")
            )
        if approval is not None and not set(
            approval["acceptance"]["required_evidence"]
        ).issubset(acceptance["evidence"]):
            diagnostics.append(
                Diagnostic(
                    path,
                    "acceptance-evidence",
                    "acceptance evidence omits an approved predicate",
                )
            )
    return diagnostics


def _global_identity_diagnostics(
    projects: dict[str, dict[str, Any]],
    initiatives: dict[str, dict[str, Any]],
    works: dict[str, dict[str, Any]],
    messages: dict[str, dict[str, dict[str, Any]]],
    receipts: dict[str, dict[str, dict[str, Any]]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    owners: dict[str, str] = {}
    execution_owners: dict[str, tuple[str, str]] = {}
    claim_runs: dict[str, tuple[str, str]] = {}
    run_claims: dict[str, tuple[str, str]] = {}

    def record(identifier: str, path: str) -> None:
        prior = owners.get(identifier)
        if prior is not None:
            diagnostics.append(
                Diagnostic(
                    path,
                    "identity-collision",
                    f"{identifier} is already owned by {prior}",
                )
            )
        else:
            owners[identifier] = path

    def record_execution_owner(identifier: str, work_id: str, path: str) -> None:
        prior = execution_owners.get(identifier)
        if prior is not None and prior[0] != work_id:
            diagnostics.append(
                Diagnostic(
                    path,
                    "identity-collision",
                    f"{identifier} is already owned by {prior[1]}",
                )
            )
        elif prior is None:
            execution_owners[identifier] = (work_id, path)

    def record_execution_pair(
        claim_id: str, worker_run_id: str, work_id: str, path: str
    ) -> None:
        record_execution_owner(claim_id, work_id, path)
        record_execution_owner(worker_run_id, work_id, path)
        prior_run = claim_runs.get(claim_id)
        if prior_run is not None and prior_run[0] != worker_run_id:
            diagnostics.append(
                Diagnostic(
                    path,
                    "identity-collision",
                    f"{claim_id} is already paired with {prior_run[0]} at {prior_run[1]}",
                )
            )
        elif prior_run is None:
            claim_runs[claim_id] = (worker_run_id, path)
        prior_claim = run_claims.get(worker_run_id)
        if prior_claim is not None and prior_claim[0] != claim_id:
            diagnostics.append(
                Diagnostic(
                    path,
                    "identity-collision",
                    f"{worker_run_id} is already paired with {prior_claim[0]} at {prior_claim[1]}",
                )
            )
        elif prior_claim is None:
            run_claims[worker_run_id] = (claim_id, path)

    for project_id in sorted(projects):
        record(project_id, f"projects/{project_id}/project.md")
    for initiative_id in sorted(initiatives):
        record(initiative_id, f"initiatives/{initiative_id}/initiative.md")
    for work_id, work in sorted(works.items()):
        work_path = f"work/{work_id}/work.md"
        record(work_id, work_path)
        claim = work["claim"]
        if claim is not None:
            record(claim["id"], work_path)
            record(claim["worker_run_id"], work_path)
            record_execution_pair(claim["id"], claim["worker_run_id"], work_id, work_path)
        for message_id in sorted(messages[work_id]):
            message_path = f"work/{work_id}/messages/{message_id}.md"
            record(message_id, message_path)
            worker_run_id = messages[work_id][message_id]["worker_run_id"]
            if worker_run_id is not None:
                record_execution_owner(worker_run_id, work_id, message_path)
        for receipt_id in sorted(receipts[work_id]):
            receipt_path = f"work/{work_id}/receipts/{receipt_id}.md"
            record(receipt_id, receipt_path)
            receipt = receipts[work_id][receipt_id]
            record_execution_pair(
                receipt["claim_id"],
                receipt["worker_run_id"],
                work_id,
                receipt_path,
            )
    return diagnostics


def _latest_review_is_clean(reviews: list[dict[str, Any]]) -> bool:
    if not reviews:
        return False
    dated_verdicts = [
        (
            datetime.fromisoformat(review["observed_at"].replace("Z", "+00:00")),
            review["verdict"],
        )
        for review in reviews
    ]
    latest = max(observed_at for observed_at, _ in dated_verdicts)
    return {
        verdict for observed_at, verdict in dated_verdicts if observed_at == latest
    } == {"clean"}


def _validate_relationships(
    projects: dict[str, dict[str, Any]],
    initiatives: dict[str, dict[str, Any]],
    works: dict[str, dict[str, Any]],
    messages: dict[str, dict[str, dict[str, Any]]],
    receipts: dict[str, dict[str, dict[str, Any]]],
) -> None:
    diagnostics = _global_identity_diagnostics(
        projects, initiatives, works, messages, receipts
    )
    repositories: dict[str, str] = {}
    active_by_project: dict[str, list[str]] = {}
    active_project_paths: dict[str, str] = {}
    for project_id, project in projects.items():
        repository = project["repository"]
        if not _valid_repository_identity(repository):
            diagnostics.append(
                Diagnostic(
                    f"projects/{project_id}/project.md",
                    "repository-identity",
                    "repository is not a canonical GitHub owner/repository pair",
                )
            )
        repository_key = _repository_identity_key(repository)
        if repository_key in repositories:
            diagnostics.append(
                Diagnostic(
                    f"projects/{project_id}/project.md",
                    "duplicate-repository",
                    f"repository already belongs to {repositories[repository_key]}",
                )
            )
        else:
            repositories[repository_key] = project_id
        if project["policy"]["repository"] != repository:
            diagnostics.append(
                Diagnostic(
                    f"projects/{project_id}/project.md",
                    "policy-repository",
                    "policy repository contradicts project repository",
                )
            )

    for work_id, work in works.items():
        path = f"work/{work_id}/work.md"
        project = projects.get(work["project_id"])
        if work["status"] in ACTIVE_STATES:
            active_key = (
                _repository_identity_key(project["repository"])
                if project is not None
                else f"missing:{work['project_id']}"
            )
            active_by_project.setdefault(active_key, []).append(work_id)
            active_project_paths.setdefault(
                active_key,
                (
                    f"projects/{work['project_id']}/project.md"
                    if project is not None
                    else path
                ),
            )
        if project is None:
            diagnostics.append(Diagnostic(path, "project-reference", "project does not exist"))
        if work["initiative_id"] is not None and work["initiative_id"] not in initiatives:
            diagnostics.append(
                Diagnostic(path, "initiative-reference", "initiative does not exist")
            )
        for field in ("dependencies", "replaces"):
            for related_id in work[field]:
                if related_id == work_id:
                    diagnostics.append(
                        Diagnostic(path, f"{field}-self", f"{field} cannot include this work")
                    )
                elif related_id not in works:
                    diagnostics.append(
                        Diagnostic(path, f"{field}-reference", f"{related_id} does not exist")
                    )
                elif field == "replaces" and works[related_id]["status"] != "cancelled":
                    diagnostics.append(
                        Diagnostic(
                            path,
                            "replaces-status",
                            f"{related_id} must be cancelled before replacement",
                        )
                    )
        native_ticket = work["native_ticket"]
        if project is not None and native_ticket is not None:
            if native_ticket["provider"] != project["native_ticket"]["provider"]:
                diagnostics.append(
                        Diagnostic(path, "ticket-provider", "ticket provider contradicts project")
                )
            if native_ticket["provider"] == "github" and not _github_object_url(
                native_ticket["url"],
                repository=project["repository"],
                object_kind="issues",
                object_id=native_ticket["id"],
            ):
                diagnostics.append(
                    Diagnostic(
                        path,
                        "ticket-url",
                        "native ticket URL contradicts its repository or identifier",
                    )
                )
        approval = work["approval"]
        if project is not None and approval is not None:
            if approval["policy"]["repository"] != project["repository"]:
                diagnostics.append(
                    Diagnostic(
                        path,
                        "approval-policy",
                        "approved policy repository contradicts the project",
                    )
                )
        current_candidate = work["claim"]["candidate"] if work["claim"] is not None else None
        if (
            project is not None
            and current_candidate is not None
            and current_candidate["repository"] != project["repository"]
        ):
            diagnostics.append(
                Diagnostic(path, "candidate-repository", "candidate belongs to another project")
            )
        diagnostics.extend(_candidate_reference_diagnostics(path, current_candidate))
        diagnostics.extend(
            _validate_lifecycle(work_id, work, messages[work_id], receipts[work_id])
        )
        current_receipt_ids = {
            receipt_id
            for receipt_id in (
                work["attempt_receipt_id"],
                work["delivery_receipt_id"],
            )
            if receipt_id is not None
        }
        for receipt_id, receipt in receipts[work_id].items():
            receipt_path = f"work/{work_id}/receipts/{receipt_id}.md"
            if receipt["approved_revision"] > work["revision"]:
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "receipt-revision",
                        "receipt approved_revision exceeds the current work revision",
                    )
                )
            transferable = receipt["handoff"] == "transferable"
            if transferable != (receipt["candidate"] is not None):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "handoff-candidate",
                        "transferable handoff and candidate must appear together",
                    )
                )
            if receipt_id in current_receipt_ids and (
                native_ticket is None
                or receipt["native_ticket"]
                != {
                    "provider": native_ticket["provider"],
                    "id": native_ticket["id"],
                }
            ):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "receipt-ticket",
                        "receipt native ticket contradicts the work",
                    )
                )
            receipt_candidate = receipt["candidate"]
            diagnostics.extend(
                _candidate_reference_diagnostics(receipt_path, receipt_candidate)
            )
            if (
                receipt_id in current_receipt_ids
                and receipt_candidate is not None
                and project is not None
                and receipt_candidate["repository"] != project["repository"]
            ):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "receipt-repository",
                        "receipt candidate belongs to another project",
                    )
                )
            if receipt_candidate is None and (receipt["validation"] or receipt["reviews"]):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "receipt-observation",
                        "candidate-bound observations require a candidate",
                    )
                )
            if receipt_candidate is not None:
                head = receipt_candidate["head_revision"]
                base = receipt_candidate["base_revision"]
                if any(item["candidate_revision"] != head for item in receipt["validation"]):
                    diagnostics.append(
                        Diagnostic(
                            receipt_path,
                            "validation-candidate",
                            "validation is not bound to the receipt candidate",
                        )
                    )
                if any(
                    item["candidate_revision"] != head
                    or item["comparison_base_revision"] != base
                    for item in receipt["reviews"]
                ):
                    diagnostics.append(
                        Diagnostic(
                            receipt_path,
                            "review-candidate",
                            "review is not bound to the receipt candidate and base",
                        )
                    )
            if receipt["outcome"] == "delivered" and (
                not transferable
                or receipt["candidate"]["pull_request"] is None
                or receipt["mutation_ownership"] != "retained"
                or any(
                    item["outcome"] != "passed"
                    for item in receipt["validation"]
                )
                or not _latest_review_is_clean(receipt["reviews"])
            ):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "delivered-receipt",
                        "delivered receipt requires a retained PR candidate "
                        "with passing validation",
                    )
                )
            if (
                receipt["outcome"] == "blocked"
                and receipt["mutation_ownership"] != "retained"
            ):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "blocked-ownership",
                        "blocked receipt must retain mutation ownership",
                    )
                )
            if receipt["outcome"] == "released" and receipt["mutation_ownership"] != "relinquished":
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "released-ownership",
                        "released receipt must relinquish mutation ownership",
                    )
                )
    for project_key, active_work in sorted(active_by_project.items()):
        if len(active_work) > 1:
            diagnostics.append(
                Diagnostic(
                    active_project_paths[project_key],
                    "parallel-assignments",
                    "multiple active assignments: " + ", ".join(sorted(active_work)),
                )
            )
    diagnostics.extend(_check_dependency_cycles(works))
    diagnostics.extend(_check_replacement_cycles(works))
    if diagnostics:
        raise MailboxValidationError(diagnostics)


def _derive_views(
    works: dict[str, dict[str, Any]],
    messages: dict[str, dict[str, dict[str, Any]]],
    readiness: dict[str, dict[str, bool]] | None,
) -> tuple[dict[str, list[str]], list[Diagnostic]]:
    views = {
        "ready": [],
        "active": [],
        "blocked": [],
        "decision_needed": [],
        "delivered": [],
        "accepted": [],
    }
    diagnostics: list[Diagnostic] = []
    active_projects = {
        work["project_id"] for work in works.values() if work["status"] in ACTIVE_STATES
    }
    for work_id, work in sorted(works.items()):
        status = work["status"]
        if status in {"active", "blocked"}:
            views["active"].append(work_id)
        if status == "blocked":
            views["blocked"].append(work_id)
        if status == "delivered":
            views["delivered"].append(work_id)
        if status == "accepted":
            views["accepted"].append(work_id)
        resolved = {
            message["resolves"]
            for message in messages[work_id].values()
            if message["resolves"] is not None
        }
        if any(
            message["kind"] == "needs-decision" and message_id not in resolved
            for message_id, message in messages[work_id].items()
        ):
            views["decision_needed"].append(work_id)

        if status != "approved":
            continue
        path = f"work/{work_id}/work.md"
        reasons: list[tuple[str, str]] = []
        if any(works[dependency]["status"] != "accepted" for dependency in work["dependencies"]):
            reasons.append(("readiness-dependencies", "not every dependency is accepted"))
        if work["project_id"] in active_projects:
            reasons.append(("readiness-project-active", "another project assignment owns mutation"))
        if work["native_ticket"] is None:
            reasons.append(("readiness-ticket-missing", "work has no native ticket"))
        supplied = (readiness or {}).get(work_id)
        for gate in ("policy", "ticket", "capability"):
            if supplied is None or gate not in supplied:
                reasons.append((f"readiness-{gate}-unknown", f"{gate} gate was not supplied"))
            elif supplied[gate] is not True:
                reasons.append((f"readiness-{gate}-failed", f"{gate} gate did not pass"))
        if reasons:
            diagnostics.extend(Diagnostic(path, code, message) for code, message in reasons)
        else:
            views["ready"].append(work_id)
    return views, diagnostics


def reconstruct_mailbox(
    root: Path,
    *,
    readiness: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    """Rebuild one deterministic snapshot directly from mailbox documents."""
    root = root.resolve()
    if not root.is_dir():
        raise _fail(root.as_posix(), "mailbox-root", "mailbox root is not a directory")
    schema_bundle = _load_schema(DEFAULT_SCHEMA)
    manifest, projects, initiatives, works, messages, receipts = _load_documents(
        root, schema_bundle
    )
    if not _valid_branch_name(manifest["canonical_branch"]):
        raise _fail(
            "atelier.yaml",
            "git-ref",
            "canonical_branch is not a valid Git branch name",
        )
    _validate_relationships(projects, initiatives, works, messages, receipts)
    if readiness is not None:
        unknown = sorted(set(readiness) - set(works))
        if unknown:
            raise _fail(
                "readiness",
                "unknown-work",
                f"readiness supplied for unknown work: {', '.join(unknown)}",
            )
        for work_id, gates in readiness.items():
            if not isinstance(gates, dict) or set(gates) - {"policy", "ticket", "capability"}:
                raise _fail(
                    f"readiness.{work_id}",
                    "unknown-gate",
                    "only policy, ticket, and capability gates are supported",
                )
            if any(not isinstance(value, bool) for value in gates.values()):
                raise _fail(
                    f"readiness.{work_id}",
                    "gate-type",
                    "readiness gates must be booleans",
                )
    views, diagnostics = _derive_views(works, messages, readiness)
    return {
        "schema": "atelier.mailbox-snapshot/v1",
        "realm_id": manifest["realm_id"],
        "canonical_branch": manifest["canonical_branch"],
        "projects": [
            {
                "id": project_id,
                "name": value["name"],
                "repository": value["repository"],
                "status": value["status"],
            }
            for project_id, value in sorted(projects.items())
        ],
        "initiatives": [
            {
                "id": initiative_id,
                "title": value["title"],
                "work": sorted(
                    work_id
                    for work_id, work in works.items()
                    if work["initiative_id"] == initiative_id
                ),
            }
            for initiative_id, value in sorted(initiatives.items())
        ],
        "work": [
            {
                "id": work_id,
                "title": value["title"],
                "project_id": value["project_id"],
                "initiative_id": value["initiative_id"],
                "status": value["status"],
                "revision": value["revision"],
                "dependencies": value["dependencies"],
                "attempt_receipt_id": value["attempt_receipt_id"],
                "delivery_receipt_id": value["delivery_receipt_id"],
            }
            for work_id, value in sorted(works.items())
        ],
        "views": views,
        "diagnostics": [item.as_dict() for item in diagnostics],
    }


def _read_readiness(path: Path | None) -> dict[str, dict[str, bool]] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise _fail(
            path.as_posix(),
            "readiness-encoding",
            "readiness input is not valid UTF-8",
        ) from error
    except OSError as error:
        raise _fail(
            path.as_posix(),
            "readiness-unreadable",
            "readiness input could not be read",
        ) from error
    except json.JSONDecodeError as error:
        raise _fail(
            path.as_posix(),
            "readiness-json",
            "readiness input is not valid JSON",
        ) from error
    if not isinstance(value, dict):
        raise _fail(path.as_posix(), "readiness-shape", "readiness must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    reconstruct = commands.add_parser("reconstruct", help="Validate and reconstruct a mailbox")
    reconstruct.add_argument("root", type=Path)
    reconstruct.add_argument("--readiness", type=Path)
    policy = commands.add_parser("validate-policy", help="Validate one project policy")
    policy.add_argument("path", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "reconstruct":
            result = reconstruct_mailbox(
                args.root,
                readiness=_read_readiness(args.readiness),
            )
        else:
            result = {
                "schema": "atelier.project-policy-check/v1",
                "status": "valid",
                "path": args.path.as_posix(),
                "policy": validate_project_policy(args.path),
            }
    except MailboxValidationError as error:
        for diagnostic in error.diagnostics:
            print(f"ERROR mailbox: {diagnostic.render()}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate v1 Atelier documents and reconstruct transient mailbox state."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"' and character == "\\":
            index += 2
            continue
        if character in {'"', "'"}:
            if quote is None:
                quote = character
            elif quote == character:
                if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                quote = None
        elif character == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.rstrip()


def _split_mapping(line: str, path: str, line_number: int) -> tuple[str, str]:
    quote: str | None = None
    for index, character in enumerate(line):
        if quote == '"' and character == "\\":
            continue
        if character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
        elif character == ":" and quote is None and (
            index + 1 == len(line) or line[index + 1].isspace()
        ):
            key = line[:index]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) is None:
                raise _fail(path, "yaml-key", f"line {line_number} has an invalid mapping key")
            return key, line[index + 1 :].lstrip()
    raise _fail(path, "yaml-mapping", f"line {line_number} must be a key/value mapping")


def _parse_scalar(value: str, path: str, line_number: int) -> Any:
    if value == "":
        raise _fail(path, "yaml-scalar", f"line {line_number} has an empty scalar")
    if value == "null" or value == "~":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
        return int(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items: list[str] = []
        start = 0
        quote: str | None = None
        escaped = False
        for index, character in enumerate(inner):
            if escaped:
                escaped = False
                continue
            if quote == '"' and character == "\\":
                escaped = True
                continue
            if character in {'"', "'"}:
                if quote is None:
                    quote = character
                elif quote == character:
                    quote = None
            elif character == "," and quote is None:
                items.append(inner[start:index].strip())
                start = index + 1
            elif character in "[]{}" and quote is None:
                raise _fail(
                    path,
                    "yaml-flow",
                    f"line {line_number} nests a flow collection",
                )
        if quote is not None:
            raise _fail(path, "yaml-string", f"line {line_number} has an unterminated string")
        items.append(inner[start:].strip())
        if any(not item for item in items):
            raise _fail(path, "yaml-flow", f"line {line_number} has an empty flow item")
        return [_parse_scalar(item, path, line_number) for item in items]
    if value == "{}":
        return {}
    if value.startswith("[") or value.startswith("{"):
        raise _fail(
            path,
            "yaml-flow",
            f"line {line_number} uses a nonempty flow collection; use block YAML",
        )
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise _fail(
                path,
                "yaml-string",
                f"line {line_number} has an invalid double-quoted string: {error.msg}",
            ) from error
        if not isinstance(parsed, str):
            raise _fail(path, "yaml-string", f"line {line_number} must contain a string")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise _fail(path, "yaml-string", f"line {line_number} has an unterminated string")
        return value[1:-1].replace("''", "'")
    if value[0] in "!&*|>@`" or value.endswith(":"):
        raise _fail(
            path,
            "yaml-feature",
            f"line {line_number} uses unsupported YAML syntax",
        )
    return value


def _parse_yaml(text: str, path: str) -> dict[str, Any]:
    source: list[tuple[int, int, str]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise _fail(path, "yaml-indent", f"line {line_number} contains a tab")
        without_comment = _strip_yaml_comment(raw)
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        if indent % 2:
            raise _fail(path, "yaml-indent", f"line {line_number} has odd indentation")
        source.append((line_number, indent, without_comment[indent:]))
    if not source:
        raise _fail(path, "yaml-empty", "document is empty")

    def parse_block(position: int, indent: int) -> tuple[Any, int]:
        if position >= len(source) or source[position][1] != indent:
            line_number = source[position][0] if position < len(source) else source[-1][0]
            raise _fail(path, "yaml-indent", f"line {line_number} has unexpected indentation")
        is_sequence = source[position][2] == "-" or source[position][2].startswith("- ")
        result: Any = [] if is_sequence else {}
        while position < len(source):
            line_number, current_indent, content = source[position]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise _fail(path, "yaml-indent", f"line {line_number} has unexpected indentation")
            item_is_sequence = content == "-" or content.startswith("- ")
            if item_is_sequence != is_sequence:
                raise _fail(path, "yaml-shape", f"line {line_number} changes collection kind")
            if is_sequence:
                remainder = content[1:].lstrip()
                if not remainder:
                    child, position = parse_block(position + 1, indent + 2)
                    result.append(child)
                    continue
                if re.match(r"[A-Za-z_][A-Za-z0-9_-]*:", remainder):
                    key, raw_value = _split_mapping(remainder, path, line_number)
                    item: dict[str, Any] = {}
                    if raw_value:
                        item[key] = _parse_scalar(raw_value, path, line_number)
                        position += 1
                    else:
                        item[key], position = parse_block(position + 1, indent + 4)
                    while position < len(source) and source[position][1] == indent + 2:
                        nested_line, _, nested_content = source[position]
                        nested_key, nested_value = _split_mapping(
                            nested_content, path, nested_line
                        )
                        if nested_key in item:
                            raise _fail(
                                path,
                                "yaml-duplicate-key",
                                f"line {nested_line} repeats {nested_key!r}",
                            )
                        if nested_value:
                            item[nested_key] = _parse_scalar(
                                nested_value, path, nested_line
                            )
                            position += 1
                        else:
                            item[nested_key], position = parse_block(
                                position + 1, indent + 4
                            )
                    result.append(item)
                    continue
                result.append(_parse_scalar(remainder, path, line_number))
                position += 1
                continue

            key, raw_value = _split_mapping(content, path, line_number)
            if key in result:
                raise _fail(
                    path,
                    "yaml-duplicate-key",
                    f"line {line_number} repeats {key!r}",
                )
            if raw_value:
                result[key] = _parse_scalar(raw_value, path, line_number)
                position += 1
            else:
                result[key], position = parse_block(position + 1, indent + 2)
        return result, position

    parsed, consumed = parse_block(0, source[0][1])
    if source[0][1] != 0:
        raise _fail(path, "yaml-indent", "the document root must not be indented")
    if consumed != len(source):
        raise _fail(path, "yaml-trailing", "document contains unparsed YAML")
    if not isinstance(parsed, dict):
        raise _fail(path, "yaml-root", "document root must be a mapping")
    return parsed


def _read_yaml(path: Path, *, frontmatter: bool) -> tuple[dict[str, Any], str]:
    label = path.as_posix()
    if path.is_symlink():
        raise _fail(label, "symlink", "normative documents must not be symbolic links")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _fail(label, "unreadable", str(error)) from error
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
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is None or parsed.utcoffset() is None:
                diagnostics.append(
                    Diagnostic(document, "schema-date-time", f"{at} must include a UTC offset")
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


def validate_project_policy(
    path: Path, *, schema_path: Path = DEFAULT_SCHEMA
) -> dict[str, Any]:
    """Validate one managed-project policy without changing it."""
    value, _ = _read_yaml(path, frontmatter=False)
    validate_document(
        value,
        path=path.as_posix(),
        schema_bundle=_load_schema(schema_path),
        expected_schema="atelier.project-policy/v1",
    )
    return value


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
    manifest, _ = _read_yaml(manifest_path, frontmatter=False)
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
        value, _ = _read_yaml(root / relative, frontmatter=True)
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
        value, _ = _read_yaml(root / relative, frontmatter=True)
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
        value, _ = _read_yaml(root / relative, frontmatter=True)
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
                child, _ = _read_yaml(path, frontmatter=True)
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


def _validate_claim(work_id: str, work: dict[str, Any]) -> list[Diagnostic]:
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
    candidate = claim["candidate"]
    publication_entries = [entry for entry in ledger if entry["phase"] == "candidate_published"]
    internally_invalid = any(
        entry["candidate_head"] is None
        or entry["acknowledged_candidate_head"] != entry["candidate_head"]
        for entry in publication_entries
    )
    current_unacknowledged = (
        candidate is not None
        and (
            not publication_entries
            or publication_entries[-1]["candidate_head"] != candidate["head_revision"]
        )
    )
    if internally_invalid or current_unacknowledged or (candidate is None and publication_entries):
        diagnostics.append(
            Diagnostic(
                path,
                "candidate-acknowledgement",
                "candidate publication history does not acknowledge the current candidate",
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
    diagnostics.extend(_validate_claim(work_id, work))

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
        if target_message is not None and target_message["blocks"] != "worker":
            diagnostics.append(
                Diagnostic(
                    f"work/{work_id}/messages/{target}.md",
                    "invalid-resolution",
                    "only a worker-blocking message can be resolved",
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

    attempt_receipt = work_receipts.get(attempt) if attempt is not None else None
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


def _validate_relationships(
    projects: dict[str, dict[str, Any]],
    initiatives: dict[str, dict[str, Any]],
    works: dict[str, dict[str, Any]],
    messages: dict[str, dict[str, dict[str, Any]]],
    receipts: dict[str, dict[str, dict[str, Any]]],
) -> None:
    diagnostics: list[Diagnostic] = []
    repositories: dict[str, str] = {}
    active_by_project: dict[str, list[str]] = {}
    for project_id, project in projects.items():
        repository = project["repository"]
        if repository in repositories:
            diagnostics.append(
                Diagnostic(
                    f"projects/{project_id}/project.md",
                    "duplicate-repository",
                    f"repository already belongs to {repositories[repository]}",
                )
            )
        repositories[repository] = project_id
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
        if work["status"] in ACTIVE_STATES:
            active_by_project.setdefault(work["project_id"], []).append(work_id)
        project = projects.get(work["project_id"])
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
        diagnostics.extend(
            _validate_lifecycle(work_id, work, messages[work_id], receipts[work_id])
        )
        for receipt_id, receipt in receipts[work_id].items():
            receipt_path = f"work/{work_id}/receipts/{receipt_id}.md"
            transferable = receipt["handoff"] == "transferable"
            if transferable != (receipt["candidate"] is not None):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "handoff-candidate",
                        "transferable handoff and candidate must appear together",
                    )
                )
            if native_ticket is None or receipt["native_ticket"] != {
                "provider": native_ticket["provider"],
                "id": native_ticket["id"],
            }:
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "receipt-ticket",
                        "receipt native ticket contradicts the work",
                    )
                )
            receipt_candidate = receipt["candidate"]
            if (
                receipt_candidate is not None
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
                or not any(item["verdict"] == "clean" for item in receipt["reviews"])
            ):
                diagnostics.append(
                    Diagnostic(
                        receipt_path,
                        "delivered-receipt",
                        "delivered receipt requires a retained PR candidate",
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
    for project_id, active_work in sorted(active_by_project.items()):
        if len(active_work) > 1:
            diagnostics.append(
                Diagnostic(
                    f"projects/{project_id}/project.md",
                    "parallel-assignments",
                    "multiple active assignments: " + ", ".join(sorted(active_work)),
                )
            )
    diagnostics.extend(_check_dependency_cycles(works))
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
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    """Rebuild one deterministic snapshot directly from mailbox documents."""
    root = root.resolve()
    if not root.is_dir():
        raise _fail(root.as_posix(), "mailbox-root", "mailbox root is not a directory")
    schema_bundle = _load_schema(schema_path)
    manifest, projects, initiatives, works, messages, receipts = _load_documents(
        root, schema_bundle
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
    except (OSError, json.JSONDecodeError) as error:
        raise _fail(path.as_posix(), "readiness-unreadable", str(error)) from error
    if not isinstance(value, dict):
        raise _fail(path.as_posix(), "readiness-shape", "readiness must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
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
                schema_path=args.schema,
            )
        else:
            result = {
                "schema": "atelier.project-policy-check/v1",
                "status": "valid",
                "path": args.path.as_posix(),
                "policy": validate_project_policy(args.path, schema_path=args.schema),
            }
    except MailboxValidationError as error:
        for diagnostic in error.diagnostics:
            print(f"ERROR mailbox: {diagnostic.render()}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

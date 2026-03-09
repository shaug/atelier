"""Tier 0 command handlers for the in-memory Beads dispatcher."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .contract import InMemoryBeadsCommandRoute
from .dispatcher import CommandEnvelope, CommandInvocation
from .store import UNSET_UPDATE_FIELD, InMemoryIssueStore


def _parse_int(value: str, *, flag: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{flag} expects an integer value") from exc


def _strip_json_flag(tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if token != "--json"]


def _claim_actor(invocation: CommandInvocation) -> str | None:
    tokens = list(invocation.global_tokens)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--actor" and index + 1 < len(tokens):
            return tokens[index + 1].strip() or None
        if token.startswith("--actor="):
            return token.partition("=")[2].strip() or None
        index += 1
    if invocation.env is None:
        return None
    actor = invocation.env.get("BD_ACTOR") or invocation.env.get("ATELIER_AGENT_ID")
    if not isinstance(actor, str):
        return None
    return actor.strip() or None


def _read_body_file(path_value: str) -> str:
    return Path(path_value).read_text(encoding="utf-8")


class InMemoryCoreIssuesHandler:
    """Handle Tier 0 lifecycle/query commands against an issue store."""

    def __init__(self, store: InMemoryIssueStore) -> None:
        self._store = store

    def __call__(
        self,
        route: InMemoryBeadsCommandRoute,
        invocation: CommandInvocation,
    ) -> CommandEnvelope:
        tokens = _strip_json_flag(invocation.command_tokens[len(route.command) :])
        try:
            if route.command == ("show",):
                return self._show(tokens)
            if route.command == ("list",):
                return self._list(tokens)
            if route.command == ("ready",):
                return self._ready(tokens)
            if route.command == ("create",):
                return self._create(tokens)
            if route.command == ("update",):
                return self._update(tokens, invocation)
            if route.command == ("close",):
                return self._close(tokens)
        except KeyError as exc:
            return CommandEnvelope(returncode=1, stderr=f"no issue found for {exc.args[0]}")
        except ValueError as exc:
            return CommandEnvelope.usage_error(str(exc))
        return CommandEnvelope.not_implemented(route)

    def _show(self, tokens: Sequence[str]) -> CommandEnvelope:
        if len(tokens) != 1:
            raise ValueError("show requires exactly one issue id")
        try:
            payload = self._store.show(tokens[0])
        except KeyError:
            return CommandEnvelope.json_payload([])
        return CommandEnvelope.json_payload([payload])

    def _list(self, tokens: Sequence[str]) -> CommandEnvelope:
        parent_id: str | None = None
        status: str | None = None
        assignee: str | None = None
        title_query: str | None = None
        title: str | None = None
        labels: list[str] = []
        include_closed = False
        limit: int | None = None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == "--all":
                include_closed = True
                index += 1
                continue
            if token in {
                "--parent",
                "--status",
                "--assignee",
                "--title",
                "--title-contains",
                "--label",
                "--limit",
            }:
                if index + 1 >= len(tokens):
                    raise ValueError(f"{token} requires a value")
                value = tokens[index + 1]
                if token == "--parent":
                    parent_id = value
                elif token == "--status":
                    status = value
                elif token == "--assignee":
                    assignee = value
                elif token == "--title":
                    title = value
                elif token == "--title-contains":
                    title_query = value
                elif token == "--label":
                    labels.append(value)
                elif token == "--limit":
                    limit = _parse_int(value, flag="--limit")
                    if limit < 0:
                        raise ValueError("--limit must be >= 0")
                index += 2
                continue
            raise ValueError(f"unsupported list flag: {token}")
        return CommandEnvelope.json_payload(
            self._store.list(
                parent_id=parent_id,
                status=status,
                assignee=assignee,
                title_query=title_query,
                title=title,
                labels=tuple(labels),
                include_closed=include_closed,
                limit=limit,
            )
        )

    def _ready(self, tokens: Sequence[str]) -> CommandEnvelope:
        parent_id: str | None = None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token != "--parent":
                raise ValueError(f"unsupported ready flag: {token}")
            if index + 1 >= len(tokens):
                raise ValueError("--parent requires a value")
            parent_id = tokens[index + 1]
            index += 2
        return CommandEnvelope.json_payload(self._store.ready(parent_id=parent_id))

    def _create(self, tokens: Sequence[str]) -> CommandEnvelope:
        title: str | None = None
        issue_type: str | None = None
        description: str | None = None
        design: str | None = None
        acceptance_criteria: str | None = None
        assignee: str | None = None
        parent_id: str | None = None
        priority: int | None = None
        estimate: int | None = None
        labels: tuple[str, ...] = ()
        body_file: str | None = None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token not in {
                "--title",
                "--type",
                "--description",
                "--body-file",
                "--design",
                "--acceptance",
                "--assignee",
                "--parent",
                "--priority",
                "--estimate",
                "--labels",
            }:
                raise ValueError(f"unsupported create flag: {token}")
            if index + 1 >= len(tokens):
                raise ValueError(f"{token} requires a value")
            value = tokens[index + 1]
            if token == "--title":
                title = value
            elif token == "--type":
                issue_type = value
            elif token == "--description":
                description = value
            elif token == "--body-file":
                body_file = value
            elif token == "--design":
                design = value
            elif token == "--acceptance":
                acceptance_criteria = value
            elif token == "--assignee":
                assignee = value
            elif token == "--parent":
                parent_id = value
            elif token == "--priority":
                priority = _parse_int(value, flag="--priority")
            elif token == "--estimate":
                estimate = _parse_int(value, flag="--estimate")
            elif token == "--labels":
                labels = tuple(label.strip() for label in value.split(",") if label.strip())
            index += 2
        if not title:
            raise ValueError("create requires --title")
        if not issue_type:
            raise ValueError("create requires --type")
        if body_file is not None:
            description = _read_body_file(body_file)
        return CommandEnvelope.json_payload(
            [
                self._store.create(
                    title=title,
                    issue_type=issue_type,
                    description=description,
                    design=design,
                    acceptance_criteria=acceptance_criteria,
                    assignee=assignee,
                    parent_id=parent_id,
                    priority=priority,
                    estimate=estimate,
                    labels=labels,
                )
            ]
        )

    def _update(
        self,
        tokens: Sequence[str],
        invocation: CommandInvocation,
    ) -> CommandEnvelope:
        if not tokens:
            raise ValueError("update requires an issue id")
        issue_id = tokens[0]
        title: str | None = None
        description: str | None = None
        design: str | None = None
        acceptance_criteria: str | None = None
        status: str | None = None
        assignee: str | None | object = None
        assignee_specified = False
        priority: int | None = None
        estimate: int | None = None
        labels: list[str] | None = None
        add_labels: list[str] = []
        remove_labels: list[str] = []
        append_notes: list[str] = []
        body_file: str | None = None
        claim = False
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token not in {
                "--claim",
                "--title",
                "--description",
                "--body-file",
                "--design",
                "--acceptance",
                "--status",
                "--assignee",
                "--priority",
                "--estimate",
                "--set-labels",
                "--add-label",
                "--remove-label",
                "--append-notes",
            }:
                raise ValueError(f"unsupported update flag: {token}")
            if token == "--claim":
                claim = True
                index += 1
                continue
            if index + 1 >= len(tokens):
                raise ValueError(f"{token} requires a value")
            value = tokens[index + 1]
            if token == "--title":
                title = value
            elif token == "--description":
                description = value
            elif token == "--body-file":
                body_file = value
            elif token == "--design":
                design = value
            elif token == "--acceptance":
                acceptance_criteria = value
            elif token == "--status":
                status = value
            elif token == "--assignee":
                assignee = value
                assignee_specified = True
            elif token == "--priority":
                priority = _parse_int(value, flag="--priority")
            elif token == "--estimate":
                estimate = _parse_int(value, flag="--estimate")
            elif token == "--set-labels":
                if labels is None:
                    labels = []
                labels.append(value)
            elif token == "--add-label":
                add_labels.append(value)
            elif token == "--remove-label":
                remove_labels.append(value)
            elif token == "--append-notes":
                append_notes.append(value)
            index += 2
        if claim:
            actor = _claim_actor(invocation)
            if actor is None:
                raise ValueError("claim requires --actor or BD_ACTOR")
            try:
                self._store.claim(issue_id, actor=actor)
            except ValueError as exc:
                return CommandEnvelope(returncode=1, stderr=str(exc))
        if body_file is not None:
            description = _read_body_file(body_file)
        if all(
            value is None
            for value in (
                title,
                description,
                design,
                acceptance_criteria,
                status,
                priority,
                estimate,
                labels,
            )
        ) and not (assignee_specified or add_labels or remove_labels or append_notes or claim):
            raise ValueError("update requires at least one field change")
        return CommandEnvelope.json_payload(
            [
                self._store.update(
                    issue_id,
                    title=title,
                    description=description,
                    design=design,
                    acceptance_criteria=acceptance_criteria,
                    status=status,
                    assignee=assignee if assignee_specified else UNSET_UPDATE_FIELD,
                    priority=priority,
                    estimate=estimate,
                    labels=None if labels is None else tuple(labels),
                    add_labels=tuple(add_labels),
                    remove_labels=tuple(remove_labels),
                    append_notes=tuple(append_notes),
                )
            ]
        )

    def _close(self, tokens: Sequence[str]) -> CommandEnvelope:
        if not tokens:
            raise ValueError("close requires an issue id")
        issue_id = tokens[0]
        reason: str | None = None
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token != "--reason":
                raise ValueError(f"unsupported close flag: {token}")
            if index + 1 >= len(tokens):
                raise ValueError("--reason requires a value")
            reason = tokens[index + 1]
            index += 2
        return CommandEnvelope.json_payload([self._store.close(issue_id, reason=reason)])


__all__ = ["InMemoryCoreIssuesHandler"]

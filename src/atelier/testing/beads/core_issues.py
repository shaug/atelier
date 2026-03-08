"""Tier 0 command handlers for the in-memory Beads dispatcher."""

from __future__ import annotations

from collections.abc import Sequence

from .contract import InMemoryBeadsCommandRoute
from .dispatcher import CommandEnvelope, CommandInvocation
from .store import InMemoryIssueStore


def _parse_int(value: str, *, flag: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{flag} expects an integer value") from exc


def _strip_json_flag(tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if token != "--json"]


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
                return self._update(tokens)
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
        return CommandEnvelope.json_payload([self._store.show(tokens[0])])

    def _list(self, tokens: Sequence[str]) -> CommandEnvelope:
        parent_id: str | None = None
        status: str | None = None
        assignee: str | None = None
        title_query: str | None = None
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
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token not in {
                "--title",
                "--type",
                "--description",
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

    def _update(self, tokens: Sequence[str]) -> CommandEnvelope:
        if not tokens:
            raise ValueError("update requires an issue id")
        issue_id = tokens[0]
        title: str | None = None
        description: str | None = None
        design: str | None = None
        acceptance_criteria: str | None = None
        status: str | None = None
        assignee: str | None = None
        priority: int | None = None
        estimate: int | None = None
        labels: list[str] | None = None
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token not in {
                "--title",
                "--description",
                "--design",
                "--acceptance",
                "--status",
                "--assignee",
                "--priority",
                "--estimate",
                "--set-labels",
            }:
                raise ValueError(f"unsupported update flag: {token}")
            if index + 1 >= len(tokens):
                raise ValueError(f"{token} requires a value")
            value = tokens[index + 1]
            if token == "--title":
                title = value
            elif token == "--description":
                description = value
            elif token == "--design":
                design = value
            elif token == "--acceptance":
                acceptance_criteria = value
            elif token == "--status":
                status = value
            elif token == "--assignee":
                assignee = value
            elif token == "--priority":
                priority = _parse_int(value, flag="--priority")
            elif token == "--estimate":
                estimate = _parse_int(value, flag="--estimate")
            elif token == "--set-labels":
                if labels is None:
                    labels = []
                labels.append(value)
            index += 2
        if all(
            value is None
            for value in (
                title,
                description,
                design,
                acceptance_criteria,
                status,
                assignee,
                priority,
                estimate,
                labels,
            )
        ):
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
                    assignee=assignee,
                    priority=priority,
                    estimate=estimate,
                    labels=None if labels is None else tuple(labels),
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

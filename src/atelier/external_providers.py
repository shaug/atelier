"""Provider contract for external ticket integrations.

Defines the capability matrix and canonical request/response shapes that
planner-initiated integrations use for external systems.

Example:
    class GithubIssuesProvider(ExternalProvider):
        slug = "github"
        display_name = "GitHub Issues"
        capabilities = ExternalProviderCapabilities(
            supports_import=True,
            supports_create=True,
            supports_link=True,
            supports_set_in_progress=True,
            supports_update=True,
            supports_state_sync=True,
        )

        def import_tickets(
            self, request: ExternalTicketImportRequest
        ) -> Sequence[ExternalTicketRecord]:
            ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .external_tickets import ExternalTicketRef


@dataclass(frozen=True)
class ExternalProviderCapabilities:
    """Capability flags for a provider integration."""

    supports_import: bool = True
    supports_create: bool = True
    supports_link: bool = True
    supports_set_in_progress: bool = True
    supports_update: bool = False
    supports_children: bool = False
    supports_state_sync: bool = False

    @property
    def supports_export(self) -> bool:
        return self.supports_create or self.supports_link

    @property
    def supports_optional_sync(self) -> bool:
        return self.supports_update or self.supports_state_sync


@dataclass(frozen=True)
class ExternalTicketSyncOptions:
    """Optional sync toggles for external ticket data."""

    include_state: bool = True
    include_body: bool = True
    include_notes: bool = True


@dataclass(frozen=True)
class ExternalTicketRecord:
    """Normalized external ticket data returned by a provider."""

    ref: ExternalTicketRef
    title: str | None = None
    body: str | None = None
    labels: tuple[str, ...] = field(default_factory=tuple)
    summary: str | None = None
    raw: dict[str, object] | None = None


@dataclass(frozen=True)
class ExternalTicketImportRequest:
    """Parameters for provider imports."""

    query: str | None = None
    limit: int | None = None
    include_closed: bool = False
    sync_options: ExternalTicketSyncOptions | None = None


@dataclass(frozen=True)
class ExternalTicketCreateRequest:
    """Parameters for creating a new external ticket."""

    bead_id: str
    title: str
    body: str | None = None
    labels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExternalTicketLinkRequest:
    """Parameters for linking an existing external ticket."""

    bead_id: str
    ticket: ExternalTicketRef
    sync_options: ExternalTicketSyncOptions | None = None


class ExternalProvider(Protocol):
    """Required provider operations for external tickets."""

    @property
    def slug(self) -> str:
        """Stable provider slug."""
        ...

    @property
    def display_name(self) -> str:
        """Human-facing provider name."""
        ...

    @property
    def capabilities(self) -> ExternalProviderCapabilities:
        """Capability flags for the provider."""
        ...

    def import_tickets(
        self, request: ExternalTicketImportRequest
    ) -> Sequence[ExternalTicketRecord]:
        """Return external tickets for planner import."""
        ...

    def create_ticket(self, request: ExternalTicketCreateRequest) -> ExternalTicketRecord:
        """Create a new external ticket from a local bead."""
        ...

    def link_ticket(self, request: ExternalTicketLinkRequest) -> ExternalTicketRecord:
        """Associate a local bead with an existing external ticket."""
        ...

    def set_in_progress(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        """Set the remote ticket to in-progress when supported."""
        ...

    def update_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str | None = None,
        body: str | None = None,
    ) -> ExternalTicketRef:
        """Optional: push local updates to the external ticket."""
        ...

    def create_child_ticket(
        self, ref: ExternalTicketRef, *, title: str, body: str | None = None
    ) -> ExternalTicketRef:
        """Optional: create a child/split ticket for review-sized work."""
        ...

    def sync_state(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        """Optional: refresh cached state for the external ticket."""
        ...

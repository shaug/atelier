from __future__ import annotations

from atelier.external_providers import ExternalProviderCapabilities


def test_external_provider_capabilities_export_flag() -> None:
    caps = ExternalProviderCapabilities(supports_create=False, supports_link=False)
    assert caps.supports_export is False

    caps = ExternalProviderCapabilities(supports_create=True, supports_link=False)
    assert caps.supports_export is True


def test_external_provider_capabilities_optional_sync() -> None:
    caps = ExternalProviderCapabilities(supports_update=False, supports_state_sync=False)
    assert caps.supports_optional_sync is False

    caps = ExternalProviderCapabilities(supports_update=True, supports_state_sync=False)
    assert caps.supports_optional_sync is True

"""Tests for integration lifecycle setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_banking import async_migrate_entry, async_setup, async_setup_entry, async_unload_entry
from custom_components.open_banking.api import OpenBankingAuthenticationError
from custom_components.open_banking.const import (
    CONF_REFRESH_INTERVAL,
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    CONF_TRANSACTION_STORAGE,
    DEFAULT_TRANSACTION_STORAGE,
    DOMAIN,
)
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed


async def test_setup_registers_callback_view(hass) -> None:
    """Integration setup registers the authorization callback endpoint."""
    with patch("custom_components.open_banking.async_register_callback_view") as register:
        assert await async_setup(hass, {}) is True

    register.assert_called_once_with(hass)


async def test_setup_entry_authenticates_refreshes_and_forwards_platforms(hass) -> None:
    """Entry setup authenticates, refreshes each subentry, and loads sensors."""
    entry = MagicMock()
    entry.data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    subentry = MagicMock(subentry_id="bank-1")
    entry.subentries = {"bank-1": subentry}
    client = MagicMock()
    client.async_authenticate = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_restore_transactions = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with (
        patch("custom_components.open_banking.OpenBankingApiClient", return_value=client),
        patch("custom_components.open_banking.OpenBankingDataUpdateCoordinator", return_value=coordinator),
    ):
        assert await async_setup_entry(hass, entry) is True

    client.async_authenticate.assert_awaited_once()
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    assert entry.runtime_data.coordinators == {"bank-1": coordinator}
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(entry, [Platform.SENSOR])


async def test_setup_entry_restores_and_persists_subentry_snapshot(hass) -> None:
    """Each subentry restores its own state and persists later coordinator updates."""

    class FakeStore:
        """Generic-compatible storage double."""

        created_with: tuple[object, int, str] | None = None
        saved: dict | None = None

        @classmethod
        def __class_getitem__(cls, item: object) -> type[FakeStore]:
            return cls

        def __init__(self, stored_hass: object, version: int, key: str) -> None:
            type(self).created_with = (stored_hass, version, key)

        async def async_load(self) -> dict:
            return {"bank-1": {"data": "restored"}, "removed-bank": {"data": "stale"}}

        async def async_save(self, data: dict) -> None:
            type(self).saved = data

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    subentry = MagicMock(subentry_id="bank-1")
    entry.subentries = {"bank-1": subentry}
    client = MagicMock()
    client.async_authenticate = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_restore_transactions = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with (
        patch("custom_components.open_banking.OpenBankingApiClient", return_value=client),
        patch("custom_components.open_banking.OpenBankingDataUpdateCoordinator", return_value=coordinator) as create,
        patch("custom_components.open_banking.Store", FakeStore),
    ):
        await async_setup_entry(hass, entry)

    assert FakeStore.created_with == (hass, 1, f"{DOMAIN}.entry-1")
    assert FakeStore.saved == {"bank-1": {"data": "restored"}}
    coordinator.async_restore_snapshot.assert_called_once_with({"data": "restored"})
    save_snapshot = create.call_args.args[4]
    await save_snapshot({"data": "updated"})
    assert FakeStore.saved == {"bank-1": {"data": "updated"}}


async def test_setup_entry_converts_invalid_credentials_to_reauth(hass) -> None:
    """Credential rejection during setup triggers Home Assistant reauthentication."""
    entry = MagicMock()
    entry.data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    client = MagicMock()
    client.async_authenticate = AsyncMock(side_effect=OpenBankingAuthenticationError)

    with (
        patch("custom_components.open_banking.OpenBankingApiClient", return_value=client),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_unload_entry_stops_coordinators_after_platform_unload(hass) -> None:
    """A successful unload cancels every coordinator's scheduled refresh."""
    entry = MagicMock()
    first = MagicMock()
    first.async_shutdown = AsyncMock()
    second = MagicMock()
    second.async_shutdown = AsyncMock()
    entry.runtime_data.coordinators = {"bank-1": first, "bank-2": second}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(hass, entry) is True
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, [Platform.SENSOR])
    first.async_shutdown.assert_awaited_once()
    second.async_shutdown.assert_awaited_once()


async def test_failed_platform_unload_keeps_coordinators_running(hass) -> None:
    """Coordinators remain active when Home Assistant cannot unload platforms."""
    entry = MagicMock()
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    entry.runtime_data.coordinators = {"bank-1": coordinator}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert await async_unload_entry(hass, entry) is False
    coordinator.async_shutdown.assert_not_awaited()


async def test_migrate_legacy_refresh_interval_to_current_defaults(hass) -> None:
    """Version 1 bank connections adopt the current daily schedule defaults."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        minor_version=1,
        subentries_data=[
            {
                "data": {CONF_REFRESH_INTERVAL: 120, "institution_id": "BANK"},
                "subentry_type": "institution",
                "title": "Bank",
                "unique_id": "req-1",
            }
        ],
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    subentry = next(iter(entry.subentries.values()))
    assert CONF_REFRESH_INTERVAL not in subentry.data
    assert subentry.data[CONF_REFRESHES_PER_DAY] == 4
    assert subentry.data[CONF_REFRESH_WINDOW_START] == "07:00:00"
    assert subentry.data[CONF_REFRESH_WINDOW_END] == "22:00:00"
    assert subentry.data["institution_id"] == "BANK"
    assert subentry.data[CONF_TRANSACTION_STORAGE] == DEFAULT_TRANSACTION_STORAGE
    assert entry.minor_version == 3


async def test_migration_preserves_current_schedule_and_is_idempotent(hass) -> None:
    """Current-format data is not overwritten by repeated migration calls."""
    schedule = {
        CONF_REFRESHES_PER_DAY: 8,
        CONF_REFRESH_WINDOW_START: "06:00:00",
        CONF_REFRESH_WINDOW_END: "18:00:00",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        minor_version=1,
        subentries_data=[
            {
                "data": schedule,
                "subentry_type": "institution",
                "title": "Bank",
                "unique_id": "req-1",
            }
        ],
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert dict(next(iter(entry.subentries.values())).data) == schedule | {
        CONF_TRANSACTION_STORAGE: DEFAULT_TRANSACTION_STORAGE
    }
    assert await async_migrate_entry(hass, entry) is True
    assert entry.minor_version == 3


async def test_migration_rejects_future_major_version(hass) -> None:
    """Downgrades from an unsupported future schema fail safely."""
    entry = MockConfigEntry(domain=DOMAIN, version=2)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False

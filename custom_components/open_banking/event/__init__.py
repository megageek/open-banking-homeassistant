"""Event platform for Open Banking transaction updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.open_banking.const import DOMAIN, TRANSACTION_STORAGE_DISABLED
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .transaction_update import OpenBankingTransactionUpdateEvent

if TYPE_CHECKING:
    from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
    from custom_components.open_banking.data import OpenBankingConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenBankingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up transaction update events for every bank connection."""
    for coordinator in entry.runtime_data.coordinators.values():
        _async_setup_coordinator(entry, coordinator, async_add_entities)


def _async_setup_coordinator(
    entry: OpenBankingConfigEntry,
    coordinator: OpenBankingDataUpdateCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Dynamically add account transaction update event entities."""
    known_entities: set[str] = set()
    subentry_id = coordinator.subentry.subentry_id

    def async_add_discovered_accounts() -> None:
        _async_cleanup_registry(entry, coordinator)
        if coordinator.transaction_mode == TRANSACTION_STORAGE_DISABLED:
            return
        entities: list[OpenBankingTransactionUpdateEvent] = []
        for account_id, account in (coordinator.data or {}).get("accounts", {}).items():
            if account_id in known_entities:
                continue
            known_entities.add(account_id)
            details = account.get("details", {})
            account_name = str(
                details.get("displayName") or details.get("name") or details.get("product") or "Bank account"
            )
            entities.append(OpenBankingTransactionUpdateEvent(coordinator, account_id, account, account_name))
        if entities:
            async_add_entities(entities, config_subentry_id=subentry_id)

    async_add_discovered_accounts()
    entry.async_on_unload(coordinator.async_add_listener(async_add_discovered_accounts))


def _async_cleanup_registry(
    entry: OpenBankingConfigEntry,
    coordinator: OpenBankingDataUpdateCoordinator,
) -> None:
    """Remove disabled or expired transaction update event entities."""
    entity_registry = er.async_get(coordinator.hass)
    device_registry = dr.async_get(coordinator.hass)
    expired_accounts = coordinator.expired_accounts
    disabled = coordinator.transaction_mode == TRANSACTION_STORAGE_DISABLED
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if (
            entity_entry.domain != Platform.EVENT
            or entity_entry.config_subentry_id != coordinator.subentry.subentry_id
            or entity_entry.device_id is None
        ):
            continue
        device = device_registry.async_get(entity_entry.device_id)
        if device is None:
            continue
        account_id = next(
            (identifier for domain, identifier in device.identifiers if domain == DOMAIN),
            None,
        )
        if disabled or account_id in expired_accounts:
            entity_registry.async_remove(entity_entry.entity_id)
            if account_id in expired_accounts and not er.async_entries_for_device(entity_registry, device.id):
                device_registry.async_remove_device(device.id)


__all__ = ["async_setup_entry"]

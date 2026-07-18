"""Sensor platform for Open Banking."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from custom_components.open_banking.const import CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES, DOMAIN
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .balance import OpenBankingBalanceSensor
from .last_refresh import OpenBankingLastRefreshSensor
from .next_refresh import OpenBankingNextRefreshSensor
from .status import OpenBankingStatusSensor

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
    """Set up sensors for every configured institution connection."""
    for coordinator in entry.runtime_data.coordinators.values():
        _async_setup_coordinator(entry, coordinator, async_add_entities)


def _async_setup_coordinator(
    entry: OpenBankingConfigEntry,
    coordinator: OpenBankingDataUpdateCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up status and dynamically discovered accounts for one institution."""
    subentry_id = coordinator.subentry.subentry_id
    async_add_entities(
        [
            OpenBankingStatusSensor(coordinator),
            OpenBankingLastRefreshSensor(coordinator),
            OpenBankingNextRefreshSensor(coordinator),
        ],
        config_subentry_id=subentry_id,
    )
    institution_identifier = (DOMAIN, subentry_id)
    selected_types = coordinator.subentry.data.get(CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES)
    known_entities: set[tuple[str, str]] = set()

    _async_cleanup_registry(entry, coordinator, set(selected_types))

    def async_add_discovered_accounts() -> None:
        """Add balance entities when accounts appear in coordinator data."""
        removed = _async_cleanup_registry(entry, coordinator, set(selected_types))
        if removed:
            coordinator.hass.async_create_task(
                coordinator.hass.config_entries.async_reload(entry.entry_id),
                f"Reload {DOMAIN} after stale entity cleanup",
            )
            return
        accounts = (coordinator.data or {}).get("accounts", {})
        names = {account_id: _account_base_name(account) for account_id, account in accounts.items()}
        duplicate_names = Counter(names.values())
        entities: list[OpenBankingBalanceSensor] = []
        for account_id, account in accounts.items():
            available_types = {balance.get("balanceType") for balance in account.get("balances", [])}
            account_name = _account_name(
                account_id,
                account,
                names[account_id],
                duplicate_names[names[account_id]] > 1,
            )
            for balance_type in selected_types:
                entity_key = (account_id, balance_type)
                if balance_type not in available_types or entity_key in known_entities:
                    continue
                known_entities.add(entity_key)
                entities.append(
                    OpenBankingBalanceSensor(
                        coordinator,
                        account_id,
                        balance_type,
                        account,
                        account_name,
                        institution_identifier,
                    )
                )
        if entities:
            async_add_entities(entities, config_subentry_id=subentry_id)

    async_add_discovered_accounts()
    entry.async_on_unload(coordinator.async_add_listener(async_add_discovered_accounts))


def _async_cleanup_registry(
    entry: OpenBankingConfigEntry,
    coordinator: OpenBankingDataUpdateCoordinator,
    selected_types: set[str],
) -> bool:
    """Remove explicitly deselected or grace-expired account entities."""
    entity_registry = er.async_get(coordinator.hass)
    device_registry = dr.async_get(coordinator.hass)
    subentry_id = coordinator.subentry.subentry_id
    expired_accounts = coordinator.expired_accounts
    expired_balances = coordinator.expired_balances
    known_accounts = coordinator.known_accounts
    known_balances = coordinator.known_balances
    removed = False

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity_entry.config_subentry_id != subentry_id or entity_entry.device_id is None:
            continue
        device = device_registry.async_get(entity_entry.device_id)
        if device is None:
            continue
        account_id = next(
            (
                identifier
                for domain, identifier in device.identifiers
                if domain == DOMAIN and identifier in known_accounts
            ),
            None,
        )
        if account_id is None:
            account_id = next(
                (
                    identifier
                    for domain, identifier in device.identifiers
                    if domain == DOMAIN and identifier in expired_accounts
                ),
                None,
            )
        if account_id is None:
            continue
        balance_key = next(
            (key for key in known_balances | expired_balances if entity_entry.unique_id == f"{key[0]}-{key[1]}"),
            None,
        )
        if balance_key is None:
            continue
        if balance_key[1] not in selected_types or account_id in expired_accounts or balance_key in expired_balances:
            entity_registry.async_remove(entity_entry.entity_id)
            removed = True

    for account_id in expired_accounts:
        device = device_registry.async_get_device(identifiers={(DOMAIN, account_id)})
        if device is not None and not er.async_entries_for_device(entity_registry, device.id):
            device_registry.async_remove_device(device.id)
            removed = True
    return removed


def _account_base_name(account: dict[str, Any]) -> str:
    """Return the bank's preferred user-facing account name."""
    details = account.get("details", {})
    return str(details.get("displayName") or details.get("name") or details.get("product") or "Bank account")


def _account_name(
    account_id: str,
    account: dict[str, Any],
    base_name: str,
    duplicate: bool,
) -> str:
    """Disambiguate duplicate account names without exposing full identifiers."""
    if not duplicate:
        return base_name
    details = account.get("details", {})
    identifier = next(
        (str(details[key]) for key in ("iban", "bban", "scan", "resourceId") if details.get(key)),
        account_id,
    )
    return f"{base_name} (…{identifier[-4:]})"


__all__ = ["async_setup_entry"]

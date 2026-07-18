"""Sensor platform for Open Banking."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from custom_components.open_banking.const import CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES, DOMAIN

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

    def async_add_discovered_accounts() -> None:
        """Add balance entities when accounts appear in coordinator data."""
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

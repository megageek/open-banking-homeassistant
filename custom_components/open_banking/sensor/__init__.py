"""Sensor platform for Open Banking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.open_banking.const import CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES, DOMAIN

from .balance import OpenBankingBalanceSensor
from .status import OpenBankingStatusSensor

if TYPE_CHECKING:
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
        entities: list[OpenBankingStatusSensor | OpenBankingBalanceSensor] = [OpenBankingStatusSensor(coordinator)]
        institution_identifier = (DOMAIN, coordinator.subentry.subentry_id)
        selected_types = coordinator.subentry.data.get(CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES)
        for account_id, account in coordinator.data.get("accounts", {}).items():
            available_types = {balance.get("balanceType") for balance in account.get("balances", [])}
            entities.extend(
                OpenBankingBalanceSensor(
                    coordinator,
                    account_id,
                    balance_type,
                    account,
                    institution_identifier,
                )
                for balance_type in selected_types
                if balance_type in available_types
            )
        async_add_entities(entities, config_subentry_id=coordinator.subentry.subentry_id)


__all__ = ["async_setup_entry"]

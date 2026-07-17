"""Tests for sensor platform entity discovery."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.open_banking.const import CONF_BALANCE_TYPES, CONF_INSTITUTION_ID, CONF_INSTITUTION_NAME
from custom_components.open_banking.sensor import async_setup_entry
from custom_components.open_banking.sensor.balance import OpenBankingBalanceSensor
from custom_components.open_banking.sensor.status import OpenBankingStatusSensor


async def test_sensor_platform_adds_status_and_selected_available_balances(hass) -> None:
    """Platform setup creates status plus only configured balance types present in API data."""
    coordinator = MagicMock()
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.subentry.data = {
        CONF_BALANCE_TYPES: ["interimAvailable", "closingBooked"],
        CONF_INSTITUTION_ID: "BANK",
        CONF_INSTITUTION_NAME: "Example Bank",
    }
    coordinator.data = {
        "accounts": {
            "account-1": {
                "details": {},
                "balances": [{"balanceType": "interimAvailable", "balanceAmount": {"amount": "1"}}],
            }
        }
    }
    entry = MagicMock()
    entry.runtime_data.coordinators = {"bank-1": coordinator}
    added: list[object] = []

    def add_entities(entities, *, config_subentry_id: str) -> None:
        assert config_subentry_id == "bank-1"
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    assert sum(isinstance(entity, OpenBankingStatusSensor) for entity in added) == 1
    assert sum(isinstance(entity, OpenBankingBalanceSensor) for entity in added) == 1

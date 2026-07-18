"""Tests for sensor platform entity discovery."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_banking.const import CONF_BALANCE_TYPES, CONF_INSTITUTION_ID, CONF_INSTITUTION_NAME
from custom_components.open_banking.sensor import _async_cleanup_registry, async_setup_entry
from custom_components.open_banking.sensor.balance import OpenBankingBalanceSensor
from custom_components.open_banking.sensor.status import OpenBankingStatusSensor
from homeassistant.helpers import device_registry as dr, entity_registry as er


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


def test_cleanup_removes_deselected_balance_entity(hass) -> None:
    """An explicit balance-type deselection removes its registry entry."""
    entry = _registry_entry(hass)
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.known_accounts = {"account-1"}
    coordinator.known_balances = {("account-1", "expected")}
    coordinator.expired_accounts = set()
    coordinator.expired_balances = set()
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id="entry-1",
        config_subentry_id="bank-1",
        identifiers={("open_banking", "account-1")},
    )
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "sensor",
        "open_banking",
        "account-1-expected",
        config_entry=entry,
        config_subentry_id="bank-1",
        device_id=device.id,
    )

    assert _async_cleanup_registry(entry, coordinator, {"interimAvailable"}) is True
    assert entity_registry.async_get(entity.entity_id) is None


def test_cleanup_removes_expired_account_device(hass) -> None:
    """A grace-expired account loses its entity and orphaned device."""
    entry = _registry_entry(hass)
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.known_accounts = set()
    coordinator.known_balances = set()
    coordinator.expired_accounts = {"account-1"}
    coordinator.expired_balances = {("account-1", "expected")}
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id="entry-1",
        config_subentry_id="bank-1",
        identifiers={("open_banking", "account-1")},
    )
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        "open_banking",
        "account-1-expected",
        config_entry=entry,
        config_subentry_id="bank-1",
        device_id=device.id,
    )

    assert _async_cleanup_registry(entry, coordinator, {"expected"}) is True
    assert device_registry.async_get(device.id) is None


def _registry_entry(hass) -> MockConfigEntry:
    """Create a registered entry with a bank subentry."""
    entry = MockConfigEntry(
        domain="open_banking",
        entry_id="entry-1",
        subentries_data=[
            {
                "data": {},
                "subentry_id": "bank-1",
                "subentry_type": "institution",
                "title": "Bank",
                "unique_id": "req-1",
            }
        ],
    )
    entry.add_to_hass(hass)
    return entry

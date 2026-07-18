"""Tests for transaction update event entity discovery and cleanup."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_banking.const import DOMAIN, TRANSACTION_STORAGE_DISABLED, TRANSACTION_STORAGE_MEMORY
from custom_components.open_banking.event import _async_cleanup_registry, async_setup_entry
from custom_components.open_banking.event.transaction_update import OpenBankingTransactionUpdateEvent
from custom_components.open_banking.sensor import _async_cleanup_registry as cleanup_sensor_registry
from homeassistant.helpers import device_registry as dr, entity_registry as er


async def test_event_platform_adds_one_event_per_enabled_account(hass) -> None:
    """Transaction-enabled accounts receive stable update event entities."""
    coordinator = MagicMock()
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.transaction_mode = TRANSACTION_STORAGE_MEMORY
    coordinator.data = {
        "accounts": {
            "account-1": {"details": {"currency": "GBP"}, "balances": []},
            "account-2": {"details": {"currency": "GBP"}, "balances": []},
        }
    }
    entry = MagicMock()
    entry.runtime_data.coordinators = {"bank-1": coordinator}
    added: list[object] = []

    def add_entities(entities, *, config_subentry_id: str) -> None:
        assert config_subentry_id == "bank-1"
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    events = [entity for entity in added if isinstance(entity, OpenBankingTransactionUpdateEvent)]
    assert {entity.unique_id for entity in events} == {
        "account-1-transaction-updates",
        "account-2-transaction-updates",
    }


def test_event_cleanup_removes_entity_when_transactions_are_disabled(hass) -> None:
    """Disabling transaction support removes its event registry entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
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
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.transaction_mode = TRANSACTION_STORAGE_DISABLED
    coordinator.expired_accounts = set()
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id="bank-1",
        identifiers={(DOMAIN, "account-1")},
    )
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "event",
        DOMAIN,
        "account-1-transaction-updates",
        config_entry=entry,
        config_subentry_id="bank-1",
        device_id=device.id,
    )

    _async_cleanup_registry(entry, coordinator)

    assert entity_registry.async_get(entity.entity_id) is None


def test_expired_account_cleanup_removes_all_transaction_entities_and_device(hass) -> None:
    """Stale summaries and events are removed before deleting the account device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
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
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.transaction_mode = TRANSACTION_STORAGE_MEMORY
    coordinator.known_accounts = set()
    coordinator.known_balances = set()
    coordinator.expired_accounts = {"account-1"}
    coordinator.expired_balances = set()
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id="bank-1",
        identifiers={(DOMAIN, "account-1")},
    )
    entity_registry = er.async_get(hass)
    summary = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "account-1-transaction-spending_today",
        config_entry=entry,
        config_subentry_id="bank-1",
        device_id=device.id,
    )
    event = entity_registry.async_get_or_create(
        "event",
        DOMAIN,
        "account-1-transaction-updates",
        config_entry=entry,
        config_subentry_id="bank-1",
        device_id=device.id,
    )

    assert cleanup_sensor_registry(entry, coordinator, set()) is True
    assert entity_registry.async_get(summary.entity_id) is None
    assert device_registry.async_get(device.id) is not None

    _async_cleanup_registry(entry, coordinator)
    assert entity_registry.async_get(event.entity_id) is None
    assert device_registry.async_get(device.id) is None

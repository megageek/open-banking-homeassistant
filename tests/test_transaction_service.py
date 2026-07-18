"""Tests for the cached transaction response action."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_banking.const import DOMAIN, TRANSACTION_STORAGE_DISABLED, TRANSACTION_STORAGE_MEMORY
from custom_components.open_banking.service_actions.get_transactions import (
    GET_TRANSACTIONS_SCHEMA,
    async_get_transactions,
)
from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

NOW = datetime(2026, 7, 18, 12, tzinfo=dt_util.UTC)


def _transaction(transaction_id: str, day: str, status: str, raw_marker: str) -> dict:
    return {
        "id": transaction_id,
        "status": status,
        "booking_date": day,
        "value_date": day,
        "amount": "-10.00",
        "currency": "GBP",
        "counterparty": "Example",
        "description": "Purchase",
        "raw": {"private": raw_marker},
    }


def _setup_account(hass, mode: str = TRANSACTION_STORAGE_MEMORY) -> tuple[str, MagicMock]:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-1")
    coordinator = MagicMock()
    coordinator.transaction_mode = mode
    coordinator.data = {"accounts": {"account-1": {"details": {"currency": "GBP"}}}}
    coordinator.transactions = {
        "account-1": {
            "booked": [
                _transaction("new", "2026-07-18", "booked", "new-raw"),
                _transaction("old", "2026-06-01", "booked", "old-raw"),
            ],
            "pending": [_transaction("pending", "2026-07-17", "pending", "pending-raw")],
            "updated_at": "2026-07-18T11:00:00+00:00",
            "truncated": False,
        }
    }
    entry.runtime_data = SimpleNamespace(coordinators={"bank-1": coordinator})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "account-1")},
        name="Main account",
    )
    return device.id, coordinator


async def test_get_transactions_defaults_are_normalized_and_private(hass) -> None:
    """Default action response returns 30 days, both statuses, and no raw data."""
    device_id, _ = _setup_account(hass)
    data = GET_TRANSACTIONS_SCHEMA({"device_id": device_id})

    with patch("custom_components.open_banking.service_actions.get_transactions.dt_util.now", return_value=NOW):
        response = await async_get_transactions(hass, ServiceCall(hass, DOMAIN, "get_transactions", data))

    assert response["date_from"] == "2026-06-19"
    assert response["date_to"] == "2026-07-18"
    assert response["status"] == "both"
    assert response["truncated"] is False
    assert [item["id"] for item in response["transactions"]] == ["new", "pending"]
    assert all("raw" not in item for item in response["transactions"])
    assert "new-raw" not in str(response)


async def test_get_transactions_filters_limits_and_includes_raw_only_on_request(hass) -> None:
    """Explicit filters and raw inclusion control the response."""
    device_id, _ = _setup_account(hass)
    data = GET_TRANSACTIONS_SCHEMA(
        {
            "device_id": device_id,
            "date_from": "2026-07-01",
            "date_to": "2026-07-18",
            "status": "booked",
            "limit": 1,
            "include_raw": True,
        }
    )

    with patch("custom_components.open_banking.service_actions.get_transactions.dt_util.now", return_value=NOW):
        response = await async_get_transactions(hass, ServiceCall(hass, DOMAIN, "get_transactions", data))

    assert response["truncated"] is False
    assert response["transactions"] == [dict(_transaction("new", "2026-07-18", "booked", "new-raw"))]


async def test_get_transactions_rejects_disabled_and_invalid_ranges(hass) -> None:
    """Disabled support and out-of-retention dates raise translated errors."""
    device_id, coordinator = _setup_account(hass, TRANSACTION_STORAGE_DISABLED)
    data = GET_TRANSACTIONS_SCHEMA({"device_id": device_id})

    with pytest.raises(ServiceValidationError) as disabled:
        await async_get_transactions(hass, ServiceCall(hass, DOMAIN, "get_transactions", data))
    assert disabled.value.translation_key == "transactions_disabled"

    coordinator.transaction_mode = TRANSACTION_STORAGE_MEMORY
    data = GET_TRANSACTIONS_SCHEMA({"device_id": device_id, "date_from": "2026-01-01", "date_to": "2026-07-18"})
    with (
        patch("custom_components.open_banking.service_actions.get_transactions.dt_util.now", return_value=NOW),
        pytest.raises(ServiceValidationError) as invalid,
    ):
        await async_get_transactions(hass, ServiceCall(hass, DOMAIN, "get_transactions", data))
    assert invalid.value.translation_key == "transaction_range_outside_retention"

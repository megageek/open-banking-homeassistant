"""Tests for transaction summary sensors."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from custom_components.open_banking.const import TRANSACTION_STORAGE_MEMORY
from custom_components.open_banking.sensor.transaction_summary import OpenBankingTransactionSummarySensor
from homeassistant.util import dt as dt_util

ACCOUNT_ID = "account-1"
NOW = datetime(2026, 7, 18, 12, tzinfo=dt_util.UTC)


def _transaction(
    amount: str,
    currency: str = "GBP",
    booking_date: str | None = None,
    value_date: str | None = None,
) -> dict:
    return {
        "id": f"{amount}-{currency}-{booking_date}-{value_date}",
        "amount": amount,
        "currency": currency,
        "booking_date": booking_date,
        "value_date": value_date,
    }


def _sensor(kind: str, pending: list[dict]) -> OpenBankingTransactionSummarySensor:
    coordinator = MagicMock()
    coordinator.transaction_mode = TRANSACTION_STORAGE_MEMORY
    coordinator.transactions = {ACCOUNT_ID: {"booked": [], "pending": pending}}
    coordinator.last_update_success = True
    return OpenBankingTransactionSummarySensor(
        coordinator,
        ACCOUNT_ID,
        kind,
        {"details": {"currency": "GBP", "iban": "GB1234"}},
        "Main account",
        ("open_banking", "bank-1"),
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("pending_outgoing", Decimal(71)),
        ("pending_outgoing_today", Decimal(10)),
        ("pending_outgoing_this_month", Decimal(30)),
    ],
)
def test_pending_summary_periods(kind: str, expected: Decimal) -> None:
    """Pending summaries apply their intended local calendar periods."""
    pending = [
        _transaction("-10", booking_date="2026-07-18"),
        _transaction("-20", value_date="2026-07-01"),
        _transaction("-30", booking_date="2026-06-30"),
        _transaction("-11"),
        _transaction("5", booking_date="2026-07-18"),
        _transaction("-40", "EUR", booking_date="2026-07-18"),
    ]

    with patch("custom_components.open_banking.sensor.transaction_summary.dt_util.now", return_value=NOW):
        assert _sensor(kind, pending).native_value == expected


@pytest.mark.parametrize(
    "kind",
    ["pending_outgoing", "pending_outgoing_today", "pending_outgoing_this_month"],
)
def test_pending_summary_unique_ids_are_stable(kind: str) -> None:
    """Each pending summary uses its translation key in the unique ID."""
    assert _sensor(kind, []).unique_id == f"{ACCOUNT_ID}-transaction-{kind}"

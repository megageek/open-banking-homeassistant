"""Tests for normalized transaction caching."""

from __future__ import annotations

from datetime import timedelta

from custom_components.open_banking.const import TRANSACTION_MAX_RECORDS
from custom_components.open_banking.coordinator.transactions import (
    normalize_transaction,
    transaction_change,
    update_account_cache,
)
from homeassistant.util import dt as dt_util


def _raw(transaction_id: str | None, days_ago: int, amount: str = "-10.00") -> dict:
    transaction = {
        "bookingDate": (dt_util.now().date() - timedelta(days=days_ago)).isoformat(),
        "transactionAmount": {"amount": amount, "currency": "GBP"},
        "creditorName": "Shop",
        "remittanceInformationUnstructured": "Purchase",
    }
    if transaction_id is not None:
        transaction["transactionId"] = transaction_id
    return transaction


def test_normalize_transaction_uses_stable_fallback_identity() -> None:
    """Transactions without bank IDs receive deterministic opaque IDs."""
    first = normalize_transaction(_raw(None, 0), "booked")
    second = normalize_transaction(_raw(None, 0), "booked")

    assert first["id"] == second["id"]
    assert len(first["id"]) == 64
    assert first["counterparty"] == "Shop"
    assert first["description"] == "Purchase"


def test_cache_merges_booked_and_replaces_pending() -> None:
    """Booked history accumulates while pending reflects the latest response."""
    existing = update_account_cache({"booked": [_raw("old", 2)], "pending": [_raw("pending-old", 0)]})

    updated = update_account_cache(
        {"booked": [_raw("new", 0), _raw("old", 2, "-11.00")], "pending": [_raw("pending-new", 0)]},
        existing,
    )

    assert {item["id"] for item in updated["booked"]} == {"old", "new"}
    assert next(item for item in updated["booked"] if item["id"] == "old")["amount"] == "-11.00"
    assert [item["id"] for item in updated["pending"]] == ["pending-new"]


def test_cache_prunes_records_outside_retention() -> None:
    """Records older than the retained window are not cached."""
    cache = update_account_cache({"booked": [_raw("current", 89), _raw("expired", 90)], "pending": []})

    assert [item["id"] for item in cache["booked"]] == ["current"]


def test_cache_retains_only_newest_five_thousand_records() -> None:
    """Oversized responses are ordered, bounded, and marked truncated."""
    booked = [
        _raw(str(index), index % 90) | {"bookingDateTime": f"2026-07-18T12:{index % 60:02d}:00Z"}
        for index in range(TRANSACTION_MAX_RECORDS + 1)
    ]

    cache = update_account_cache({"booked": booked, "pending": []})

    assert len(cache["booked"]) == TRANSACTION_MAX_RECORDS
    assert cache["truncated"] is True
    assert cache["booked"] == sorted(cache["booked"], key=lambda item: (item["booking_date"], item["id"]), reverse=True)


def test_initial_transaction_change_has_sanitized_zero_counts() -> None:
    """Initial history is visible without being reported as newly observed."""
    cache = update_account_cache({"booked": [_raw("existing", 0)], "pending": []})

    change = transaction_change(None, cache, "GBP")

    assert change == {
        "cache_updated_at": cache["updated_at"],
        "initial_population": True,
        "booked_added_count": 0,
        "booked_updated_count": 0,
        "booked_removed_count": 0,
        "pending_added_count": 0,
        "pending_updated_count": 0,
        "pending_removed_count": 0,
        "currency_mismatch_count": 0,
    }
    assert "existing" not in str(change)
    assert "amount" not in str(change)


def test_transaction_change_counts_meaningful_cache_differences() -> None:
    """Change metadata distinguishes additions, updates, removals, and mismatches."""
    previous = update_account_cache(
        {
            "booked": [_raw("booked-updated", 1), _raw("booked-removed", 1)],
            "pending": [_raw("pending-updated", 0), _raw("pending-removed", 0)],
        }
    )
    current = update_account_cache(
        {
            "booked": [_raw("booked-updated", 1, "-12"), _raw("booked-added", 0)],
            "pending": [
                _raw("pending-updated", 0, "-13"),
                _raw("pending-added", 0) | {"transactionAmount": {"amount": "-10", "currency": "EUR"}},
            ],
        }
    )

    change = transaction_change(previous, current, "GBP")

    assert change is not None
    assert change["booked_added_count"] == 1
    assert change["booked_updated_count"] == 1
    assert change["booked_removed_count"] == 1
    assert change["pending_added_count"] == 1
    assert change["pending_updated_count"] == 1
    assert change["pending_removed_count"] == 1
    assert change["currency_mismatch_count"] == 1


def test_transaction_change_ignores_timestamp_and_raw_payload_only_changes() -> None:
    """Refresh timestamps and bank-specific raw differences do not emit updates."""
    previous = update_account_cache({"booked": [_raw("same", 0)], "pending": []})
    current = update_account_cache({"booked": [_raw("same", 0) | {"extraBankField": "changed"}], "pending": []})

    assert transaction_change(previous, current, "GBP") is None

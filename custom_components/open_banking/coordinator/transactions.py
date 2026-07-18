"""Transaction cache normalization and aggregation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

from custom_components.open_banking.const import TRANSACTION_MAX_RECORDS, TRANSACTION_RETENTION_DAYS
from homeassistant.util import dt as dt_util

type TransactionCache = dict[str, dict[str, Any]]


def update_account_cache(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize, prune, and bound one account transaction response."""
    cutoff = dt_util.now().date() - timedelta(days=TRANSACTION_RETENTION_DAYS - 1)
    booked_by_id = {
        str(item["id"]): item
        for item in (existing or {}).get("booked", [])
        if isinstance(item, dict) and item.get("id") and _within_retention(item, cutoff)
    }
    booked_by_id.update({item["id"]: item for item in _normalize_many(payload.get("booked", []), "booked", cutoff)})
    booked = list(booked_by_id.values())
    pending = _normalize_many(payload.get("pending", []), "pending", cutoff)
    combined = sorted(booked + pending, key=transaction_sort_key, reverse=True)
    truncated = len(combined) > TRANSACTION_MAX_RECORDS
    combined = combined[:TRANSACTION_MAX_RECORDS]
    return {
        "booked": [item for item in combined if item["status"] == "booked"],
        "pending": [item for item in combined if item["status"] == "pending"],
        "updated_at": dt_util.utcnow().isoformat(),
        "truncated": truncated,
    }


def normalize_transaction(raw: dict[str, Any], status: str) -> dict[str, Any]:
    """Return a stable transaction representation while retaining the raw object."""
    amount_data = raw.get("transactionAmount", {})
    amount = str(amount_data.get("amount", ""))
    currency = str(amount_data.get("currency", ""))
    booking_date = _date_value(raw, "bookingDate", "bookingDateTime")
    value_date = _date_value(raw, "valueDate", "valueDateTime")
    counterparty = str(
        raw.get("creditorName")
        or raw.get("debtorName")
        or raw.get("merchantName")
        or raw.get("ultimateCreditor")
        or raw.get("ultimateDebtor")
        or ""
    )
    remittance = raw.get("remittanceInformationUnstructuredArray")
    description = str(
        raw.get("remittanceInformationUnstructured")
        or (" ".join(str(item) for item in remittance) if isinstance(remittance, list) else "")
        or raw.get("additionalInformation")
        or raw.get("proprietaryBankTransactionCode")
        or raw.get("bankTransactionCode")
        or ""
    )
    transaction_id = raw.get("transactionId") or raw.get("internalTransactionId") or raw.get("entryReference")
    if not transaction_id:
        identity = json.dumps(
            [status, booking_date, value_date, amount, currency, counterparty, description],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        transaction_id = sha256(identity.encode()).hexdigest()
    return {
        "id": str(transaction_id),
        "status": status,
        "booking_date": booking_date,
        "value_date": value_date,
        "amount": amount,
        "currency": currency,
        "counterparty": counterparty,
        "description": description,
        "raw": raw,
    }


def transaction_date(transaction: dict[str, Any]) -> date | None:
    """Return the best available calendar date."""
    value = transaction.get("booking_date") or transaction.get("value_date")
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def transaction_sort_key(transaction: dict[str, Any]) -> tuple[str, str]:
    """Return a newest-first compatible transaction sort key."""
    return (str(transaction.get("booking_date") or transaction.get("value_date") or ""), str(transaction["id"]))


def transaction_amount(transaction: dict[str, Any]) -> Decimal | None:
    """Return a decimal transaction amount."""
    try:
        return Decimal(str(transaction["amount"]))
    except InvalidOperation, KeyError:
        return None


def _normalize_many(items: Any, status: str, cutoff: date) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        transaction = normalize_transaction(raw, status)
        item_date = transaction_date(transaction)
        if (item_date is not None and item_date >= cutoff) or (status == "pending" and item_date is None):
            by_id[transaction["id"]] = transaction
    return list(by_id.values())


def _within_retention(transaction: dict[str, Any], cutoff: date) -> bool:
    item_date = transaction_date(transaction)
    return item_date is not None and item_date >= cutoff


def _date_value(raw: dict[str, Any], date_key: str, datetime_key: str) -> str | None:
    value = raw.get(date_key) or raw.get(datetime_key)
    return str(value)[:10] if value else None

"""Transaction history response action."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import voluptuous as vol

from custom_components.open_banking.const import DOMAIN, TRANSACTION_RETENTION_DAYS, TRANSACTION_STORAGE_DISABLED
from custom_components.open_banking.coordinator.transactions import transaction_date, transaction_sort_key
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util

ATTR_DATE_FROM = "date_from"
ATTR_DATE_TO = "date_to"
ATTR_STATUS = "status"
ATTR_LIMIT = "limit"
ATTR_INCLUDE_RAW = "include_raw"

GET_TRANSACTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_DATE_FROM): cv.date,
        vol.Optional(ATTR_DATE_TO): cv.date,
        vol.Optional(ATTR_STATUS, default="both"): vol.In({"booked", "pending", "both"}),
        vol.Optional(ATTR_LIMIT, default=100): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional(ATTR_INCLUDE_RAW, default=False): cv.boolean,
    }
)


async def async_get_transactions(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Return filtered cached transactions for one account device."""
    account_id, account, coordinator = _resolve_account(hass, str(call.data[ATTR_DEVICE_ID]))
    if coordinator.transaction_mode == TRANSACTION_STORAGE_DISABLED:
        raise _validation_error("transactions_disabled")
    cache = coordinator.transactions.get(account_id)
    if cache is None:
        raise _validation_error("transactions_unavailable")

    today = dt_util.now().date()
    earliest = today - timedelta(days=TRANSACTION_RETENTION_DAYS - 1)
    date_from = call.data.get(ATTR_DATE_FROM, today - timedelta(days=29))
    date_to = call.data.get(ATTR_DATE_TO, today)
    if not isinstance(date_from, date) or not isinstance(date_to, date) or date_from > date_to:
        raise _validation_error("invalid_transaction_range")
    if date_from < earliest or date_to > today:
        raise _validation_error(
            "transaction_range_outside_retention",
            {"earliest": earliest.isoformat(), "today": today.isoformat()},
        )

    status = str(call.data[ATTR_STATUS])
    transactions = [
        transaction
        for selected_status in (("booked", "pending") if status == "both" else (status,))
        for transaction in cache.get(selected_status, [])
        if (item_date := transaction_date(transaction)) is not None and date_from <= item_date <= date_to
    ]
    transactions.sort(key=transaction_sort_key, reverse=True)
    limit = int(call.data[ATTR_LIMIT])
    include_raw = bool(call.data[ATTR_INCLUDE_RAW])
    response_transactions = []
    for transaction in transactions[:limit]:
        item = {key: value for key, value in transaction.items() if key != "raw"}
        if include_raw:
            item["raw"] = transaction.get("raw", {})
        response_transactions.append(item)

    details = account.get("details", {})
    device = dr.async_get(hass).async_get(str(call.data[ATTR_DEVICE_ID]))
    return {
        "account": {
            "device_id": call.data[ATTR_DEVICE_ID],
            "name": device.name_by_user or device.name if device else "Bank account",
            "currency": details.get("currency"),
        },
        "cache_updated_at": cache.get("updated_at"),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "status": status,
        "truncated": bool(cache.get("truncated")) or len(transactions) > limit,
        "transactions": response_transactions,
    }


def _resolve_account(hass: HomeAssistant, device_id: str) -> tuple[str, dict[str, Any], Any]:
    """Resolve an Open Banking account device to its coordinator data."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise _validation_error("transaction_device_missing")
    account_id = next((value for domain, value in device.identifiers if domain == DOMAIN), None)
    if account_id is None:
        raise _validation_error("transaction_account_required")
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
            continue
        for coordinator in entry.runtime_data.coordinators.values():
            account = (coordinator.data or {}).get("accounts", {}).get(account_id)
            if account is not None:
                return account_id, account, coordinator
    raise _validation_error("transaction_account_unknown")


def _validation_error(key: str, placeholders: dict[str, str] | None = None) -> ServiceValidationError:
    """Return a translated transaction action validation error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )

"""Tests for sensitive diagnostic redaction."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.open_banking.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_credentials_and_account_data(hass) -> None:
    """Diagnostics do not expose credentials or bank identifiers."""
    entry = MagicMock()
    entry.data = {"secret_id": "id", "secret_key": "key"}
    entry.subentries = {}
    entry.runtime_data.coordinators = {
        "bank": MagicMock(data={"accounts": {"account-id": {"details": {"iban": "secret"}}}})
    }
    entry.runtime_data.coordinators["bank"].diagnostics.return_value = {
        "last_attempt_success": False,
        "last_error_category": "rate_limited",
        "quota_limit": 4,
        "quota_remaining": 0,
        "missing_accounts": 1,
        "missing_balances": 2,
    }

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["secret_id"] == "**REDACTED**"
    assert diagnostics["entry"]["secret_key"] == "**REDACTED**"
    assert diagnostics["coordinators"]["bank"]["accounts"] == "**REDACTED**"
    assert diagnostics["coordinators"]["bank"]["operational"] == {
        "last_attempt_success": False,
        "last_error_category": "rate_limited",
        "quota_limit": 4,
        "quota_remaining": 0,
        "missing_accounts": 1,
        "missing_balances": 2,
    }

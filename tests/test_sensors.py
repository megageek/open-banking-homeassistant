"""Tests for Open Banking sensor values."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from custom_components.open_banking.sensor.balance import OpenBankingBalanceSensor
from custom_components.open_banking.sensor.status import OpenBankingStatusSensor


def test_balance_sensor_uses_decimal_and_api_currency() -> None:
    """Balance values remain decimal-safe and retain native currency."""
    coordinator = MagicMock()
    coordinator.data = {
        "accounts": {
            "account": {
                "details": {"name": "Current account", "product": "Current"},
                "balances": [
                    {
                        "balanceType": "interimAvailable",
                        "balanceAmount": {"amount": "123.45", "currency": "GBP"},
                    }
                ],
            }
        }
    }
    sensor = OpenBankingBalanceSensor(
        coordinator,
        "account",
        "interimAvailable",
        coordinator.data["accounts"]["account"],
        "Current account",
        ("open_banking", "institution"),
    )

    assert sensor.native_value == Decimal("123.45")
    assert sensor.native_unit_of_measurement == "GBP"


def test_balance_sensor_handles_missing_and_invalid_data() -> None:
    """Malformed or missing balances do not raise from entity properties."""
    coordinator = MagicMock()
    coordinator.data = {"requisition": {"status": "UA"}, "accounts": {"account": {"balances": []}}}
    sensor = OpenBankingBalanceSensor(coordinator, "account", "expected", {}, "Account", ("open_banking", "bank"))

    assert sensor.native_value is None
    assert sensor.native_unit_of_measurement is None
    assert sensor.available is False


def test_status_sensor_exposes_requisition_status() -> None:
    """The diagnostic sensor reports the current requisition status."""
    coordinator = MagicMock()
    coordinator.data = {"requisition": {"status": "LN"}}
    coordinator.subentry.subentry_id = "bank-1"
    coordinator.subentry.data = {"institution_id": "BANK", "institution_name": "Bank"}

    sensor = OpenBankingStatusSensor(coordinator)

    assert sensor.native_value == "ln"
    assert sensor.unique_id == "bank-1-status"

"""Tests for Open Banking sensor values."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from custom_components.open_banking.sensor.balance import OpenBankingBalanceSensor


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
        ("open_banking", "institution"),
    )

    assert sensor.native_value == Decimal("123.45")
    assert sensor.native_unit_of_measurement == "GBP"

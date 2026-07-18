"""Tests for transaction update events and native triggers."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.open_banking.event.transaction_update import (
    EVENT_TRANSACTIONS_UPDATED,
    OpenBankingTransactionUpdateEvent,
)
from custom_components.open_banking.trigger import (
    OpenBankingNewBookedTransactionsTrigger,
    OpenBankingPendingTransactionsChangedTrigger,
    OpenBankingTransactionTrigger,
    async_get_triggers,
)
from homeassistant.components.event.const import ATTR_EVENT_TYPE
from homeassistant.core import State


def _attributes(**changes: int | bool | str | None) -> dict:
    attributes = {
        ATTR_EVENT_TYPE: EVENT_TRANSACTIONS_UPDATED,
        "cache_updated_at": "2026-07-18T12:00:00+00:00",
        "initial_population": False,
        "booked_added_count": 0,
        "booked_updated_count": 0,
        "booked_removed_count": 0,
        "pending_added_count": 0,
        "pending_updated_count": 0,
        "pending_removed_count": 0,
        "currency_mismatch_count": 0,
    }
    attributes.update(changes)
    return attributes


def _trigger(trigger_type: type[OpenBankingTransactionTrigger]) -> OpenBankingTransactionTrigger:
    config = MagicMock(options=None, target={"entity_id": "event.account_transaction_updates"})
    return trigger_type(MagicMock(), config)


async def test_native_trigger_discovery() -> None:
    """All three banking-specific triggers are registered."""
    assert set(await async_get_triggers(MagicMock())) == {
        "transactions_updated",
        "new_booked_transactions",
        "pending_transactions_changed",
    }


def test_native_trigger_predicates() -> None:
    """Specialized triggers select only their matching sanitized counts."""
    unchanged = State("event.account_transaction_updates", "2026-07-18T12:00:00+00:00", _attributes())
    booked = State(
        "event.account_transaction_updates",
        "2026-07-18T12:01:00+00:00",
        _attributes(booked_added_count=1),
    )
    pending = State(
        "event.account_transaction_updates",
        "2026-07-18T12:02:00+00:00",
        _attributes(pending_removed_count=1),
    )

    assert _trigger(OpenBankingTransactionTrigger).is_valid_state(unchanged)
    assert _trigger(OpenBankingNewBookedTransactionsTrigger).is_valid_state(booked)
    assert not _trigger(OpenBankingNewBookedTransactionsTrigger).is_valid_state(unchanged)
    assert _trigger(OpenBankingPendingTransactionsChangedTrigger).is_valid_state(pending)
    assert not _trigger(OpenBankingPendingTransactionsChangedTrigger).is_valid_state(booked)


def test_event_entity_emits_each_change_sequence_once() -> None:
    """The event entity publishes a sanitized coordinator change only once."""
    change = {key: value for key, value in _attributes().items() if key != ATTR_EVENT_TYPE}
    coordinator = MagicMock()
    coordinator.transaction_change_for_account.return_value = (1, change)
    entity = OpenBankingTransactionUpdateEvent(
        coordinator,
        "account-secret-id",
        {"details": {"currency": "GBP", "iban": "GB1234"}},
        "Main account",
    )
    entity.async_write_ha_state = MagicMock()

    assert entity._async_emit_latest_change() is True  # noqa: SLF001
    assert entity._async_emit_latest_change() is False  # noqa: SLF001
    assert entity.state_attributes == _attributes()
    assert entity.unique_id == "account-secret-id-transaction-updates"
    assert entity.async_write_ha_state.call_count == 1
    assert "account-secret-id" not in str(entity.state_attributes)
    assert "GBP" not in str(entity.state_attributes)


async def test_native_trigger_attachment_runs_only_for_matching_changes(hass) -> None:
    """Attached native triggers target an entity and filter its change counts."""
    entity_id = "event.account_transaction_updates"
    config = MagicMock(options=None, target={"entity_id": entity_id})
    trigger = OpenBankingNewBookedTransactionsTrigger(hass, config)
    run_action = MagicMock()
    remove = await trigger.async_attach_runner(run_action)
    hass.states.async_set(entity_id, "2026-07-18T12:00:00+00:00", _attributes())
    await hass.async_block_till_done()

    hass.states.async_set(
        entity_id,
        "2026-07-18T12:01:00+00:00",
        _attributes(pending_added_count=1),
    )
    await hass.async_block_till_done()
    run_action.assert_not_called()

    hass.states.async_set(
        entity_id,
        "2026-07-18T12:02:00+00:00",
        _attributes(booked_added_count=1),
    )
    await hass.async_block_till_done()
    run_action.assert_called_once()
    assert run_action.call_args.args[0]["entity_id"] == entity_id
    remove()

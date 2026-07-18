"""Native automation triggers for Open Banking transaction updates."""

from __future__ import annotations

from typing import ClassVar

from custom_components.open_banking.event.transaction_update import EVENT_TRANSACTIONS_UPDATED
from homeassistant.components.event import DOMAIN as EVENT_DOMAIN
from homeassistant.components.event.const import ATTR_EVENT_TYPE
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.automation import DomainSpec
from homeassistant.helpers.trigger import ENTITY_STATE_TRIGGER_SCHEMA, EntityTriggerBase, Trigger


class OpenBankingTransactionTrigger(EntityTriggerBase):
    """Base trigger for a transaction update event entity."""

    _domain_specs = {EVENT_DOMAIN: DomainSpec()}
    _schema = ENTITY_STATE_TRIGGER_SCHEMA
    _required_positive_attributes: ClassVar[tuple[str, ...]] = ()

    def is_valid_transition(self, from_state: State, to_state: State) -> bool:
        """Accept each newly emitted event entity state."""
        return from_state.state not in {STATE_UNAVAILABLE, to_state.state}

    def is_valid_state(self, state: State) -> bool:
        """Match Open Banking update attributes required by this trigger."""
        return (
            state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            and state.attributes.get(ATTR_EVENT_TYPE) == EVENT_TRANSACTIONS_UPDATED
            and (
                not self._required_positive_attributes
                or any(int(state.attributes.get(key, 0)) > 0 for key in self._required_positive_attributes)
            )
        )


class OpenBankingNewBookedTransactionsTrigger(OpenBankingTransactionTrigger):
    """Trigger when newly observed booked transactions are added."""

    _required_positive_attributes = ("booked_added_count",)


class OpenBankingPendingTransactionsChangedTrigger(OpenBankingTransactionTrigger):
    """Trigger when pending transactions are added, updated, or removed."""

    _required_positive_attributes = (
        "pending_added_count",
        "pending_updated_count",
        "pending_removed_count",
    )


TRIGGERS: dict[str, type[Trigger]] = {
    "transactions_updated": OpenBankingTransactionTrigger,
    "new_booked_transactions": OpenBankingNewBookedTransactionsTrigger,
    "pending_transactions_changed": OpenBankingPendingTransactionsChangedTrigger,
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return native Open Banking automation triggers."""
    return TRIGGERS

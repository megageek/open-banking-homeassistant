"""Tests for bank-connection coordinator updates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.open_banking.api import (
    OpenBankingAuthenticationError,
    OpenBankingCommunicationError,
    OpenBankingRateLimitError,
)
from custom_components.open_banking.const import (
    CONF_REFRESH_INTERVAL,
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_REQUISITION_ID,
)
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util


async def test_coordinator_loads_accounts_and_balances(hass) -> None:
    """A linked requisition is expanded into account details and balances."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": ["account-1"]})
    client.async_get_account_details = AsyncMock(return_value={"account": {"currency": "GBP"}})
    client.async_get_account_balances = AsyncMock(
        return_value={
            "balances": [
                {
                    "balanceType": "interimAvailable",
                    "balanceAmount": {"amount": "12.34", "currency": "GBP"},
                }
            ]
        }
    )
    entry = MagicMock()
    subentry = MagicMock()
    subentry.subentry_id = "bank-1"
    subentry.data = {CONF_REQUISITION_ID: "req-1", CONF_REFRESH_INTERVAL: 240}
    coordinator = OpenBankingDataUpdateCoordinator(hass, entry, subentry, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["accounts"]["account-1"]["details"]["currency"] == "GBP"
    assert data["accounts"]["account-1"]["balances"][0]["balanceType"] == "interimAvailable"


async def test_coordinator_does_not_load_unlinked_accounts(hass) -> None:
    """An incomplete requisition reports status without requesting account data."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "UA", "accounts": ["account-1"]})
    client.async_get_account_details = AsyncMock()
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data == {"requisition": {"status": "UA", "accounts": ["account-1"]}, "accounts": {}}
    client.async_get_account_details.assert_not_awaited()


async def test_coordinator_tracks_agreement_expiry_and_creates_warning(hass) -> None:
    """A linked agreement nearing expiry creates a fixable warning."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": [], "agreement": "agreement-1"})
    client.async_get_end_user_agreement = AsyncMock(
        return_value={
            "accepted": (dt_util.utcnow() - timedelta(days=84)).isoformat(),
            "access_valid_for_days": 90,
        }
    )
    coordinator = _coordinator(hass, client)

    await coordinator._async_update_data()  # noqa: SLF001

    issue = ir.async_get(hass).async_get_issue("open_banking", "requisition_expiry_bank-1")
    assert issue is not None
    assert issue.translation_key == "requisition_expiring"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert coordinator.requisition_expires_at is not None
    await coordinator.async_shutdown()


async def test_expired_requisition_stops_scheduling_and_creates_error(hass) -> None:
    """An expired requisition stops polling and raises an error repair."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "EX", "accounts": []})
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["requisition"]["status"] == "EX"
    assert coordinator._next_refresh_at is None  # noqa: SLF001
    issue = ir.async_get(hass).async_get_issue("open_banking", "requisition_expiry_bank-1")
    assert issue is not None
    assert issue.translation_key == "requisition_expired"
    assert issue.severity is ir.IssueSeverity.ERROR


def test_snapshot_for_previous_requisition_is_not_restored(hass) -> None:
    """Replacing a requisition invalidates its persisted coordinator snapshot."""
    coordinator = _coordinator(hass, MagicMock())

    coordinator.async_restore_snapshot(
        {
            "requisition_id": "old-requisition",
            "data": {"requisition": {"status": "LN"}, "accounts": {}},
        }
    )

    assert coordinator.data is None


def test_matching_snapshot_restores_data_and_scheduler_state(hass) -> None:
    """A persisted snapshot for the current requisition restores all known state."""
    coordinator = _coordinator(hass, MagicMock())
    next_refresh = "2026-07-18T09:00:00+00:00"
    blocked_until = "2026-07-18T08:30:00+00:00"
    expires_at = "2026-08-01T00:00:00+00:00"

    coordinator.async_restore_snapshot(
        {
            "requisition_id": "req-1",
            "data": {"requisition": {"status": "LN"}, "accounts": {}},
            "quota_limit": 4,
            "quota_blocked_until": blocked_until,
            "next_refresh_at": next_refresh,
            "agreement_id": "agreement-1",
            "requisition_expires_at": expires_at,
        }
    )

    assert coordinator.data == {"requisition": {"status": "LN"}, "accounts": {}}
    assert coordinator._quota_limit == 4  # noqa: SLF001
    assert coordinator._quota_blocked_until == datetime.fromisoformat(blocked_until)  # noqa: SLF001
    assert coordinator._next_refresh_at == datetime.fromisoformat(next_refresh)  # noqa: SLF001
    assert coordinator.requisition_expires_at == datetime.fromisoformat(expires_at)


@pytest.mark.parametrize(
    "agreement_data",
    [
        {"accepted": "invalid", "access_valid_for_days": 90},
        {"accepted": "2026-01-01T00:00:00+00:00"},
        {"accepted": "2026-01-01T00:00:00+00:00", "access_valid_for_days": "invalid"},
    ],
)
async def test_invalid_agreement_metadata_is_ignored(hass, agreement_data: dict[str, object]) -> None:
    """Malformed optional agreement metadata does not fail account updates."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": [], "agreement": "agreement-1"})
    client.async_get_end_user_agreement = AsyncMock(return_value=agreement_data)
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["requisition"]["status"] == "LN"
    assert coordinator.requisition_expires_at is None
    await coordinator.async_shutdown()


async def test_agreement_lookup_failure_does_not_block_account_update(hass) -> None:
    """Expiry metadata is best-effort when the agreement endpoint is unavailable."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": [], "agreement": "agreement-1"})
    client.async_get_end_user_agreement = AsyncMock(side_effect=OpenBankingCommunicationError("offline"))
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["accounts"] == {}
    assert coordinator.requisition_expires_at is None
    await coordinator.async_shutdown()


async def test_first_refresh_fetches_when_no_snapshot(hass) -> None:
    """Startup performs a normal first refresh when no data was restored."""
    coordinator = _coordinator(hass, MagicMock())

    with patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_config_entry_first_refresh",
        AsyncMock(),
    ) as first_refresh:
        await coordinator.async_config_entry_first_refresh()

    first_refresh.assert_awaited_once_with()


async def test_first_refresh_schedules_future_restored_update(hass) -> None:
    """Fresh restored data waits for its persisted future refresh time."""
    coordinator = _coordinator(hass, MagicMock())
    future = dt_util.utcnow() + timedelta(hours=1)
    coordinator.async_set_updated_data({"requisition": {"status": "LN"}, "accounts": {}})
    coordinator._next_refresh_at = future  # noqa: SLF001
    coordinator.async_refresh = AsyncMock()  # type: ignore[method-assign]
    coordinator._schedule_at = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001

    await coordinator.async_config_entry_first_refresh()

    coordinator.async_refresh.assert_not_awaited()
    coordinator._schedule_at.assert_called_once_with(future)  # noqa: SLF001


async def test_first_refresh_catches_up_after_missed_update(hass) -> None:
    """Stale restored data refreshes immediately and schedules its next slot."""
    save_snapshot = AsyncMock()
    coordinator = _coordinator(hass, MagicMock(), save_snapshot=save_snapshot)
    data = {"requisition": {"status": "LN"}, "accounts": {}}
    coordinator.async_set_updated_data(data)
    coordinator._next_refresh_at = dt_util.utcnow() - timedelta(minutes=1)  # noqa: SLF001
    coordinator.async_refresh = AsyncMock()  # type: ignore[method-assign]
    next_refresh = dt_util.utcnow() + timedelta(hours=1)
    coordinator._next_scheduled_time = MagicMock(return_value=next_refresh)  # type: ignore[method-assign]  # noqa: SLF001
    coordinator._schedule_at = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001

    await coordinator.async_config_entry_first_refresh()

    coordinator.async_refresh.assert_awaited_once()
    coordinator._schedule_at.assert_called_once_with(next_refresh)  # noqa: SLF001
    save_snapshot.assert_awaited_once()


async def test_scheduled_refresh_arranges_and_saves_next_update(hass) -> None:
    """A timer refresh persists the next planned update after completion."""
    save_snapshot = AsyncMock()
    coordinator = _coordinator(hass, MagicMock(), save_snapshot=save_snapshot)
    coordinator.async_set_updated_data({"requisition": {"status": "LN"}, "accounts": {}})
    coordinator.async_refresh = AsyncMock()  # type: ignore[method-assign]
    next_refresh = dt_util.utcnow() + timedelta(hours=1)
    coordinator._next_scheduled_time = MagicMock(return_value=next_refresh)  # type: ignore[method-assign]  # noqa: SLF001
    coordinator._schedule_at = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001

    await coordinator._async_scheduled_refresh(dt_util.utcnow())  # noqa: SLF001

    coordinator.async_refresh.assert_awaited_once()
    coordinator._schedule_at.assert_called_once_with(next_refresh)  # noqa: SLF001
    save_snapshot.assert_awaited_once()


def test_quota_uses_most_restrictive_limit_and_exhaustion(hass) -> None:
    """Observed account quotas cap refreshes and defer them after exhaustion."""
    client = MagicMock()
    client.account_rate_limits = {
        ("account-1", "details"): SimpleNamespace(limit=6, remaining=5, reset_after=100),
        ("account-1", "balances"): SimpleNamespace(limit=4, remaining=0, reset_after=300),
    }
    coordinator = _coordinator(hass, client)
    before = dt_util.utcnow()

    coordinator._update_quota({"account-1": {}})  # noqa: SLF001

    assert coordinator._quota_limit == 4  # noqa: SLF001
    assert coordinator._quota_blocked_until is not None  # noqa: SLF001
    assert coordinator._quota_blocked_until >= before + timedelta(seconds=300)  # noqa: SLF001


def test_next_refresh_respects_active_window_and_quota(monkeypatch, hass) -> None:
    """Scheduling selects a future active-window slot using the quota cap."""
    now = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    coordinator = _coordinator(hass, MagicMock())
    coordinator.subentry.data = {
        CONF_REQUISITION_ID: "req-1",
        CONF_REFRESHES_PER_DAY: 6,
        CONF_REFRESH_WINDOW_START: "08:00:00",
        CONF_REFRESH_WINDOW_END: "20:00:00",
    }
    coordinator._quota_limit = 4  # noqa: SLF001

    assert coordinator._next_scheduled_time() == datetime(2026, 7, 17, 8, 0, tzinfo=UTC)  # noqa: SLF001


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpenBankingAuthenticationError("expired"), ConfigEntryAuthFailed),
        (OpenBankingCommunicationError("offline"), UpdateFailed),
        (OpenBankingRateLimitError("wait", 30), UpdateFailed),
    ],
)
async def test_coordinator_normalizes_api_failures(hass, error: Exception, expected: type[Exception]) -> None:
    """API failures are translated into Home Assistant coordinator failures."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(side_effect=error)

    with pytest.raises(expected):
        await _coordinator(hass, client)._async_update_data()  # noqa: SLF001


def _coordinator(
    hass,
    client: MagicMock,
    *,
    save_snapshot: AsyncMock | None = None,
) -> OpenBankingDataUpdateCoordinator:
    """Create a coordinator with standard test configuration."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    subentry = MagicMock()
    subentry.subentry_id = "bank-1"
    subentry.title = "Example Bank"
    subentry.data = {CONF_REQUISITION_ID: "req-1", CONF_REFRESH_INTERVAL: 240}
    return OpenBankingDataUpdateCoordinator(hass, entry, subentry, client, save_snapshot)

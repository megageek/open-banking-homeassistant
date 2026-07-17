"""Data coordinator for one bank connection subentry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from typing import Any

from custom_components.open_banking.api import (
    OpenBankingApiClient,
    OpenBankingApiError,
    OpenBankingAuthenticationError,
    OpenBankingRateLimitError,
)
from custom_components.open_banking.const import (
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_REQUISITION_ID,
    DEFAULT_REFRESH_WINDOW_END,
    DEFAULT_REFRESH_WINDOW_START,
    DEFAULT_REFRESHES_PER_DAY,
    DOMAIN,
    LOGGER,
    REQUISITION_LINKED,
)
from custom_components.open_banking.data import OpenBankingConfigEntry
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

type SaveSnapshot = Callable[[dict[str, Any]], Awaitable[None]]


async def _async_noop_save(_: dict[str, Any]) -> None:
    """Discard a snapshot when persistence is not configured."""


class OpenBankingDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch requisition, account metadata, and balances for a subentry."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: OpenBankingConfigEntry,
        subentry: ConfigSubentry,
        client: OpenBankingApiClient,
        save_snapshot: SaveSnapshot | None = None,
    ) -> None:
        """Initialize the coordinator."""
        self.subentry = subentry
        self.client = client
        self._save_snapshot = save_snapshot or _async_noop_save
        self._cancel_scheduled_refresh: CALLBACK_TYPE | None = None
        self._quota_limit: int | None = None
        self._quota_blocked_until: datetime | None = None
        self._next_refresh_at: datetime | None = None
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{subentry.subentry_id}",
            update_interval=None,
            always_update=False,
        )

    def async_restore_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """Restore saved coordinator and scheduling state."""
        if snapshot and isinstance(snapshot.get("data"), dict):
            self.async_set_updated_data(snapshot["data"])
            self._quota_limit = _optional_int(snapshot.get("quota_limit"))
            self._quota_blocked_until = _parse_datetime(snapshot.get("quota_blocked_until"))
            self._next_refresh_at = _parse_datetime(snapshot.get("next_refresh_at"))

    async def async_config_entry_first_refresh(self) -> None:
        """Refresh on setup only when data is absent or its schedule was missed."""
        if self.data is None:
            await super().async_config_entry_first_refresh()
            return
        if self._next_refresh_at is None or dt_util.utcnow() >= self._next_refresh_at:
            await self.async_refresh()
            if self._cancel_scheduled_refresh is None:
                self._schedule_at(self._next_scheduled_time())
                await self._save_snapshot(self._snapshot(self.data))
            return
        self._schedule_at(self._next_refresh_at)

    async def async_shutdown(self) -> None:
        """Cancel the scheduled refresh."""
        if self._cancel_scheduled_refresh is not None:
            self._cancel_scheduled_refresh()
            self._cancel_scheduled_refresh = None
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all data for this bank connection."""
        try:
            requisition = await self.client.async_get_requisition(str(self.subentry.data[CONF_REQUISITION_ID]))
            accounts: dict[str, dict[str, Any]] = {}
            if requisition.get("status") == REQUISITION_LINKED:
                for account_id in requisition.get("accounts", []):
                    details_response = await self.client.async_get_account_details(account_id)
                    balances_response = await self.client.async_get_account_balances(account_id)
                    accounts[account_id] = {
                        "details": details_response.get("account", {}),
                        "balances": balances_response.get("balances", []),
                    }
        except OpenBankingAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except OpenBankingRateLimitError as err:
            if err.retry_after is not None:
                self._quota_blocked_until = dt_util.utcnow() + timedelta(seconds=err.retry_after)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=err.retry_after,
            ) from err
        except UpdateFailed:
            raise
        except OpenBankingApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        else:
            data = {"requisition": requisition, "accounts": accounts}
            self._update_quota(accounts)
            self._schedule_at(self._next_scheduled_time())
            await self._save_snapshot(self._snapshot(data))
            return data

    async def _async_scheduled_refresh(self, _: datetime) -> None:
        """Run one scheduled refresh and arrange the next one."""
        self._cancel_scheduled_refresh = None
        await self.async_refresh()
        if self._cancel_scheduled_refresh is None:
            self._schedule_at(self._next_scheduled_time())
            if self.data is not None:
                await self._save_snapshot(self._snapshot(self.data))

    def _schedule_at(self, when: datetime) -> None:
        """Schedule the coordinator at a UTC timestamp."""
        if self._cancel_scheduled_refresh is not None:
            self._cancel_scheduled_refresh()
        self._next_refresh_at = dt_util.as_utc(when)
        self._cancel_scheduled_refresh = async_track_point_in_utc_time(
            self.hass,
            self._async_scheduled_refresh,
            self._next_refresh_at,
        )

    def _next_scheduled_time(self) -> datetime:
        """Return the next active-window slot allowed by known quotas."""
        now = dt_util.now()
        earliest = now
        if self._quota_blocked_until is not None:
            earliest = max(earliest, dt_util.as_local(self._quota_blocked_until))
        refreshes = int(self.subentry.data.get(CONF_REFRESHES_PER_DAY, DEFAULT_REFRESHES_PER_DAY))
        if self._quota_limit is not None:
            refreshes = min(refreshes, self._quota_limit)
        start = time.fromisoformat(str(self.subentry.data.get(CONF_REFRESH_WINDOW_START, DEFAULT_REFRESH_WINDOW_START)))
        end = time.fromisoformat(str(self.subentry.data.get(CONF_REFRESH_WINDOW_END, DEFAULT_REFRESH_WINDOW_END)))
        for day_offset in range(8):
            day = now.date() + timedelta(days=day_offset)
            first = datetime.combine(day, start, tzinfo=now.tzinfo)
            last = datetime.combine(day, end, tzinfo=now.tzinfo)
            spacing = (last - first) / max(refreshes - 1, 1)
            for index in range(refreshes):
                slot = first + spacing * index
                if slot > now and slot >= earliest:
                    return dt_util.as_utc(slot)
        raise RuntimeError("Unable to calculate the next refresh time")

    def _update_quota(self, accounts: dict[str, dict[str, Any]]) -> None:
        """Apply the most restrictive quota observed during this refresh."""
        rate_limits = getattr(self.client, "account_rate_limits", None)
        if not isinstance(rate_limits, dict):
            return
        quotas = [
            quota
            for account_id in accounts
            for scope in ("details", "balances")
            if (quota := rate_limits.get((account_id, scope))) is not None
        ]
        if not quotas:
            return
        self._quota_limit = min(quota.limit for quota in quotas)
        exhausted = [quota.reset_after for quota in quotas if quota.remaining <= 0]
        self._quota_blocked_until = dt_util.utcnow() + timedelta(seconds=max(exhausted)) if exhausted else None

    def _snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return JSON-serializable coordinator state."""
        return {
            "data": data,
            "next_refresh_at": self._next_refresh_at.isoformat() if self._next_refresh_at else None,
            "quota_limit": self._quota_limit,
            "quota_blocked_until": self._quota_blocked_until.isoformat() if self._quota_blocked_until else None,
        }


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a stored timestamp."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    """Return an integer or None from stored data."""
    return value if isinstance(value, int) else None

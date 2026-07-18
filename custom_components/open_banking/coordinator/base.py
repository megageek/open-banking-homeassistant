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
    MISSING_ENTITY_REFRESH_THRESHOLD,
    REQUISITION_EXPIRY_ISSUE_PREFIX,
    REQUISITION_EXPIRY_WARNING,
    REQUISITION_LINKED,
)
from custom_components.open_banking.data import OpenBankingConfigEntry
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
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
        self._open_banking_config_entry = config_entry
        self._save_snapshot = save_snapshot or _async_noop_save
        self._cancel_scheduled_refresh: CALLBACK_TYPE | None = None
        self._quota_limit: int | None = None
        self._quota_remaining: int | None = None
        self._quota_blocked_until: datetime | None = None
        self._last_refresh_at: datetime | None = None
        self._next_refresh_at: datetime | None = None
        self._last_attempt_at: datetime | None = None
        self._last_attempt_success: bool | None = None
        self._last_error_category: str | None = None
        self._last_error_at: datetime | None = None
        self._agreement_id: str | None = None
        self._requisition_expires_at: datetime | None = None
        self._known_accounts: set[str] = set()
        self._known_balances: set[tuple[str, str]] = set()
        self._missing_accounts: dict[str, int] = {}
        self._missing_balances: dict[tuple[str, str], int] = {}
        self._expired_accounts: set[str] = set()
        self._expired_balances: set[tuple[str, str]] = set()
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{subentry.subentry_id}",
            update_interval=None,
            always_update=False,
        )

    @property
    def requisition_expires_at(self) -> datetime | None:
        """Return the known consent expiry timestamp."""
        return self._requisition_expires_at

    @property
    def last_refresh_at(self) -> datetime | None:
        """Return when account data was last refreshed successfully."""
        return self._last_refresh_at

    @property
    def next_refresh_at(self) -> datetime | None:
        """Return when the next account data refresh is scheduled."""
        return self._next_refresh_at

    @property
    def known_accounts(self) -> set[str]:
        """Return account identifiers known to this connection."""
        return self._known_accounts.copy()

    @property
    def known_balances(self) -> set[tuple[str, str]]:
        """Return balance keys known to this connection."""
        return self._known_balances.copy()

    @property
    def expired_accounts(self) -> set[str]:
        """Return accounts whose absence crossed the cleanup threshold."""
        return self._expired_accounts.copy()

    @property
    def expired_balances(self) -> set[tuple[str, str]]:
        """Return balances whose absence crossed the cleanup threshold."""
        return self._expired_balances.copy()

    def async_restore_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """Restore saved coordinator and scheduling state."""
        if snapshot and snapshot.get("requisition_id") != self.subentry.data.get(CONF_REQUISITION_ID):
            return
        if snapshot:
            if isinstance(snapshot.get("data"), dict):
                self.async_set_updated_data(snapshot["data"])
            self._quota_limit = _optional_int(snapshot.get("quota_limit"))
            self._quota_remaining = _optional_int(snapshot.get("quota_remaining"))
            self._quota_blocked_until = _parse_datetime(snapshot.get("quota_blocked_until"))
            self._last_refresh_at = _parse_datetime(snapshot.get("last_refresh_at"))
            self._next_refresh_at = _parse_datetime(snapshot.get("next_refresh_at"))
            self._last_attempt_at = _parse_datetime(snapshot.get("last_attempt_at"))
            last_attempt_success = snapshot.get("last_attempt_success")
            self._last_attempt_success = last_attempt_success if isinstance(last_attempt_success, bool) else None
            last_error_category = snapshot.get("last_error_category")
            self._last_error_category = last_error_category if isinstance(last_error_category, str) else None
            self._last_error_at = _parse_datetime(snapshot.get("last_error_at"))
            agreement_id = snapshot.get("agreement_id")
            self._agreement_id = agreement_id if isinstance(agreement_id, str) else None
            self._requisition_expires_at = _parse_datetime(snapshot.get("requisition_expires_at"))
            self._known_accounts = _string_set(snapshot.get("known_accounts"))
            self._known_balances = _balance_set(snapshot.get("known_balances"))
            self._missing_accounts = _missing_account_counts(snapshot.get("missing_accounts"))
            self._missing_balances = _missing_balance_counts(snapshot.get("missing_balances"))
            self._expired_accounts = _string_set(snapshot.get("expired_accounts"))
            self._expired_balances = _balance_set(snapshot.get("expired_balances"))

    async def async_config_entry_first_refresh(self) -> None:
        """Refresh on setup only when data is absent or its schedule was missed."""
        if self.data is not None:
            self._update_expiry_issue(str(self.data.get("requisition", {}).get("status", "")))
        if self.data is None:
            await super().async_config_entry_first_refresh()
            return
        if self._next_refresh_at is None or dt_util.utcnow() >= self._next_refresh_at:
            await self.async_refresh()
            if self._cancel_scheduled_refresh is None and not self._is_expired():
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
        self._last_attempt_at = dt_util.utcnow()
        self._last_attempt_success = False
        self._expired_accounts.clear()
        self._expired_balances.clear()
        try:
            requisition = await self.client.async_get_requisition(str(self.subentry.data[CONF_REQUISITION_ID]))
            accounts: dict[str, dict[str, Any]] = {}
            if requisition.get("status") == REQUISITION_LINKED:
                await self._async_update_requisition_expiry(requisition)
                for account_id in requisition.get("accounts", []):
                    details_response = await self.client.async_get_account_details(account_id)
                    balances_response = await self.client.async_get_account_balances(account_id)
                    accounts[account_id] = {
                        "details": details_response.get("account", {}),
                        "balances": balances_response.get("balances", []),
                    }
        except OpenBankingAuthenticationError as err:
            await self._async_record_failure("authentication_failed")
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except OpenBankingRateLimitError as err:
            if err.retry_after is not None:
                self._quota_blocked_until = dt_util.utcnow() + timedelta(seconds=err.retry_after)
            await self._async_record_failure("rate_limited")
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=err.retry_after,
            ) from err
        except UpdateFailed:
            await self._async_record_failure("update_failed")
            raise
        except OpenBankingApiError as err:
            await self._async_record_failure("update_failed")
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        else:
            data = {"requisition": requisition, "accounts": accounts}
            self._last_refresh_at = dt_util.utcnow()
            self._last_attempt_success = True
            self._update_quota(accounts)
            status = str(requisition.get("status", ""))
            if status == REQUISITION_LINKED:
                self._update_missing_entities(accounts)
            self._update_expiry_issue(status)
            if status == "EX":
                if self._cancel_scheduled_refresh is not None:
                    self._cancel_scheduled_refresh()
                    self._cancel_scheduled_refresh = None
                self._next_refresh_at = None
            else:
                self._schedule_at(self._next_scheduled_time())
            data["last_refresh_at"] = self._last_refresh_at.isoformat()
            data["next_refresh_at"] = self._next_refresh_at.isoformat() if self._next_refresh_at else None
            await self._save_snapshot(self._snapshot(data))
            return data

    async def _async_record_failure(self, category: str) -> None:
        """Persist a sanitized refresh failure without replacing cached data."""
        self._last_error_category = category
        self._last_error_at = dt_util.utcnow()
        await self._save_snapshot(self._snapshot(self.data))

    def _update_missing_entities(self, accounts: dict[str, dict[str, Any]]) -> None:
        """Advance absence counters after a successful linked refresh."""
        current_accounts = set(accounts)
        current_balances = {
            (account_id, str(balance["balanceType"]))
            for account_id, account in accounts.items()
            for balance in account.get("balances", [])
            if balance.get("balanceType")
        }

        for account_id in current_accounts:
            self._known_accounts.add(account_id)
            self._missing_accounts.pop(account_id, None)
        for account_id in self._known_accounts - current_accounts:
            count = self._missing_accounts.get(account_id, 0) + 1
            if count >= MISSING_ENTITY_REFRESH_THRESHOLD:
                self._expired_accounts.add(account_id)
            else:
                self._missing_accounts[account_id] = count

        for balance_key in current_balances:
            self._known_balances.add(balance_key)
            self._missing_balances.pop(balance_key, None)
        for balance_key in self._known_balances - current_balances:
            if balance_key[0] not in current_accounts:
                continue
            count = self._missing_balances.get(balance_key, 0) + 1
            if count >= MISSING_ENTITY_REFRESH_THRESHOLD:
                self._expired_balances.add(balance_key)
            else:
                self._missing_balances[balance_key] = count

        for account_id in self._expired_accounts:
            self._known_accounts.discard(account_id)
            self._missing_accounts.pop(account_id, None)
            self._known_balances = {key for key in self._known_balances if key[0] != account_id}
            self._missing_balances = {
                key: value for key, value in self._missing_balances.items() if key[0] != account_id
            }
        for balance_key in self._expired_balances:
            self._known_balances.discard(balance_key)
            self._missing_balances.pop(balance_key, None)

    async def _async_update_requisition_expiry(self, requisition: dict[str, Any]) -> None:
        """Fetch the linked agreement and calculate the consent expiry."""
        agreement = requisition.get("agreement") or requisition.get("agreements")
        if not isinstance(agreement, str) or not agreement:
            return
        if agreement == self._agreement_id and self._requisition_expires_at is not None:
            return
        try:
            agreement_data = await self.client.async_get_end_user_agreement(agreement)
        except OpenBankingApiError:
            LOGGER.debug("Unable to retrieve agreement expiry for %s", self.subentry.subentry_id)
            return
        accepted = dt_util.parse_datetime(str(agreement_data.get("accepted", "")))
        try:
            valid_days = int(agreement_data["access_valid_for_days"])
        except KeyError, TypeError, ValueError:
            return
        if accepted is None:
            return
        self._agreement_id = agreement
        self._requisition_expires_at = accepted + timedelta(days=valid_days)

    def _update_expiry_issue(self, status: str) -> None:
        """Create, update, or clear the requisition expiry repair issue."""
        issue_id = f"{REQUISITION_EXPIRY_ISSUE_PREFIX}_{self.subentry.subentry_id}"
        expired = status == "EX"
        warning = (
            self._requisition_expires_at is not None
            and self._requisition_expires_at - dt_util.utcnow() <= REQUISITION_EXPIRY_WARNING
        )
        if not expired and not warning:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        expiry = self._requisition_expires_at
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            data={
                "entry_id": self._open_banking_config_entry.entry_id,
                "subentry_id": self.subentry.subentry_id,
            },
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR if expired else ir.IssueSeverity.WARNING,
            translation_key="requisition_expired" if expired else "requisition_expiring",
            translation_placeholders={
                "institution": str(self.subentry.title),
                "expires": expiry.date().isoformat() if expiry else "unknown",
            },
        )

    async def _async_scheduled_refresh(self, _: datetime) -> None:
        """Run one scheduled refresh and arrange the next one."""
        self._cancel_scheduled_refresh = None
        await self.async_refresh()
        if self._cancel_scheduled_refresh is None and not self._is_expired():
            self._schedule_at(self._next_scheduled_time())
            if self.data is not None:
                await self._save_snapshot(self._snapshot(self.data))

    def _is_expired(self) -> bool:
        """Return whether the current requisition is expired."""
        return self.data is not None and self.data.get("requisition", {}).get("status") == "EX"

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
        self._quota_remaining = min(quota.remaining for quota in quotas)
        exhausted = [quota.reset_after for quota in quotas if quota.remaining <= 0]
        self._quota_blocked_until = dt_util.utcnow() + timedelta(seconds=max(exhausted)) if exhausted else None

    def _snapshot(self, data: dict[str, Any] | None) -> dict[str, Any]:
        """Return JSON-serializable coordinator state."""
        return {
            "data": data,
            "requisition_id": self.subentry.data.get(CONF_REQUISITION_ID),
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
            "next_refresh_at": self._next_refresh_at.isoformat() if self._next_refresh_at else None,
            "quota_limit": self._quota_limit,
            "quota_remaining": self._quota_remaining,
            "quota_blocked_until": self._quota_blocked_until.isoformat() if self._quota_blocked_until else None,
            "last_attempt_at": self._last_attempt_at.isoformat() if self._last_attempt_at else None,
            "last_attempt_success": self._last_attempt_success,
            "last_error_category": self._last_error_category,
            "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
            "agreement_id": self._agreement_id,
            "requisition_expires_at": (
                self._requisition_expires_at.isoformat() if self._requisition_expires_at else None
            ),
            "known_accounts": sorted(self._known_accounts),
            "known_balances": [list(key) for key in sorted(self._known_balances)],
            "missing_accounts": self._missing_accounts,
            "missing_balances": [[*key, count] for key, count in sorted(self._missing_balances.items())],
            "expired_accounts": sorted(self._expired_accounts),
            "expired_balances": [list(key) for key in sorted(self._expired_balances)],
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return sanitized operational diagnostics."""
        return {
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
            "next_refresh_at": self._next_refresh_at.isoformat() if self._next_refresh_at else None,
            "last_attempt_at": self._last_attempt_at.isoformat() if self._last_attempt_at else None,
            "last_attempt_success": self._last_attempt_success,
            "last_error_category": self._last_error_category,
            "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
            "quota_limit": self._quota_limit,
            "quota_remaining": self._quota_remaining,
            "quota_blocked_until": self._quota_blocked_until.isoformat() if self._quota_blocked_until else None,
            "requisition_expires_at": (
                self._requisition_expires_at.isoformat() if self._requisition_expires_at else None
            ),
            "missing_accounts": len(self._missing_accounts),
            "missing_balances": len(self._missing_balances),
        }


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a stored timestamp."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    """Return an integer or None from stored data."""
    return value if isinstance(value, int) else None


def _string_set(value: Any) -> set[str]:
    """Restore a set of strings from storage."""
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _balance_set(value: Any) -> set[tuple[str, str]]:
    """Restore balance keys from storage."""
    if not isinstance(value, list):
        return set()
    return {
        (item[0], item[1])
        for item in value
        if isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) for part in item)
    }


def _missing_account_counts(value: Any) -> dict[str, int]:
    """Restore missing-account counters from storage."""
    if not isinstance(value, dict):
        return {}
    return {key: count for key, count in value.items() if isinstance(key, str) and isinstance(count, int)}


def _missing_balance_counts(value: Any) -> dict[tuple[str, str], int]:
    """Restore missing-balance counters from storage."""
    if not isinstance(value, list):
        return {}
    return {
        (item[0], item[1]): item[2]
        for item in value
        if (
            isinstance(item, list)
            and len(item) == 3
            and isinstance(item[0], str)
            and isinstance(item[1], str)
            and isinstance(item[2], int)
        )
    }

"""Tests for the external authorization callback."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
import pytest

from custom_components.open_banking.callback import (
    CallbackState,
    OpenBankingCallbackView,
    async_register_callback_view,
    async_store_callback_state,
)
from custom_components.open_banking.const import DATA_CALLBACK_STATES, DOMAIN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.http import KEY_HASS
from homeassistant.util import dt as dt_util


async def test_callback_advances_subentry_flow_and_consumes_state(hass) -> None:
    """A valid callback advances its flow and can only be used once."""
    state = CallbackState("flow-1", dt_util.now() + timedelta(minutes=1), True)
    hass.data[DOMAIN] = {DATA_CALLBACK_STATES: {"token": state}}
    hass.config_entries.subentries.async_configure = AsyncMock(return_value={"type": FlowResultType.EXTERNAL_STEP_DONE})
    request = MagicMock()
    request.app = {KEY_HASS: hass}
    request.query = {"state": "token"}

    response = await OpenBankingCallbackView().get(request)

    assert response.status == 200
    assert "token" not in hass.data[DOMAIN][DATA_CALLBACK_STATES]
    hass.config_entries.subentries.async_configure.assert_awaited_once_with("flow-1", {"state": "token"})


async def test_callback_advances_repair_flow(hass) -> None:
    """A repair callback advances the repairs flow manager."""
    state = CallbackState("repair-1", dt_util.now() + timedelta(minutes=1), False, True)
    hass.data[DOMAIN] = {DATA_CALLBACK_STATES: {"token": state}}
    manager = MagicMock()
    manager.async_configure = AsyncMock(return_value={"type": FlowResultType.EXTERNAL_STEP_DONE})
    request = MagicMock()
    request.app = {KEY_HASS: hass}
    request.query = {"state": "token"}

    with patch("custom_components.open_banking.callback.repairs_flow_manager", return_value=manager):
        response = await OpenBankingCallbackView().get(request)

    assert response.status == 200
    manager.async_configure.assert_awaited_once_with("repair-1", {"state": "token"})


async def test_callback_rejects_unavailable_repair_manager(hass) -> None:
    """Repair callbacks fail clearly when Home Assistant has no repairs manager."""
    state = CallbackState("repair-1", dt_util.now() + timedelta(minutes=1), False, True)
    hass.data[DOMAIN] = {DATA_CALLBACK_STATES: {"token": state}}
    request = MagicMock()
    request.app = {KEY_HASS: hass}
    request.query = {"state": "token"}

    with (
        patch("custom_components.open_banking.callback.repairs_flow_manager", return_value=None),
        pytest.raises(web.HTTPBadRequest) as caught,
    ):
        await OpenBankingCallbackView().get(request)

    assert "repair flow is unavailable" in caught.value.text


@pytest.mark.parametrize("token", [None, "unknown", "expired"])
async def test_callback_rejects_invalid_or_expired_state(hass, token: str | None) -> None:
    """Missing, unknown, and expired callback state is rejected."""
    hass.data[DOMAIN] = {
        DATA_CALLBACK_STATES: {"expired": CallbackState("flow-1", dt_util.now() - timedelta(seconds=1), False)}
    }
    request = MagicMock()
    request.app = {KEY_HASS: hass}
    request.query = {} if token is None else {"state": token}

    with pytest.raises(web.HTTPBadRequest) as caught:
        await OpenBankingCallbackView().get(request)
    assert "Invalid or expired" in caught.value.text


async def test_callback_rejects_inactive_flow(hass) -> None:
    """A callback cannot complete a flow that no longer awaits it."""
    hass.data[DOMAIN] = {
        DATA_CALLBACK_STATES: {"token": CallbackState("flow-1", dt_util.now() + timedelta(minutes=1), False)}
    }
    hass.config_entries.flow.async_configure = AsyncMock(return_value={"type": FlowResultType.ABORT})
    request = MagicMock()
    request.app = {KEY_HASS: hass}
    request.query = {"state": "token"}

    with pytest.raises(web.HTTPBadRequest) as caught:
        await OpenBankingCallbackView().get(request)
    assert "no longer active" in caught.value.text


def test_callback_view_is_registered_once(hass) -> None:
    """Repeated integration setup does not register duplicate callback views."""
    hass.http = MagicMock()

    async_register_callback_view(hass)
    async_register_callback_view(hass)

    assert hass.data[DOMAIN][DATA_CALLBACK_STATES] == {}
    hass.http.register_view.assert_called_once()


def test_stored_callback_state_expires(hass) -> None:
    """Stored callback state is removed by its scheduled expiry handler."""
    hass.data[DOMAIN] = {DATA_CALLBACK_STATES: {}}
    state = CallbackState("flow-1", dt_util.now() + timedelta(minutes=1), False)

    with patch("custom_components.open_banking.callback.async_call_later") as call_later:
        async_store_callback_state(hass, "token", state)

    assert hass.data[DOMAIN][DATA_CALLBACK_STATES]["token"] is state
    call_later.call_args.args[2](dt_util.now())
    assert "token" not in hass.data[DOMAIN][DATA_CALLBACK_STATES]

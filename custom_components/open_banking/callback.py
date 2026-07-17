"""HTTP callback used to complete external bank authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import CALLBACK_PATH, CALLBACK_TTL, DATA_CALLBACK_STATES, DOMAIN


@dataclass
class CallbackState:
    """One pending, single-use external authorization callback."""

    flow_id: str
    expires_at: datetime
    is_subentry: bool


class OpenBankingCallbackView(HomeAssistantView):
    """Receive the browser redirect from GoCardless."""

    url = CALLBACK_PATH
    name = "api:open_banking:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Validate state and advance the matching subentry flow."""
        hass: HomeAssistant = request.app[KEY_HASS]
        state_token = request.query.get("state")
        states: dict[str, CallbackState] = hass.data[DOMAIN][DATA_CALLBACK_STATES]
        callback_state = states.pop(state_token, None) if state_token else None
        if callback_state is None or callback_state.expires_at <= dt_util.now():
            raise web.HTTPBadRequest(text="Invalid or expired Open Banking authorization state")

        if callback_state.is_subentry:
            result = await hass.config_entries.subentries.async_configure(
                callback_state.flow_id,
                {"state": state_token},
            )
        else:
            result = await hass.config_entries.flow.async_configure(
                callback_state.flow_id,
                {"state": state_token},
            )
        if result.get("type") is not FlowResultType.EXTERNAL_STEP_DONE:
            raise web.HTTPBadRequest(text="The Open Banking configuration flow is no longer active")
        return web.Response(
            text="<html><body><p>Authorization received. You may close this window.</p>"
            "<script>window.close()</script></body></html>",
            content_type="text/html",
        )


def async_register_callback_view(hass: HomeAssistant) -> None:
    """Register the callback endpoint once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if DATA_CALLBACK_STATES in domain_data:
        return
    domain_data[DATA_CALLBACK_STATES] = {}
    hass.http.register_view(OpenBankingCallbackView())


def async_store_callback_state(hass: HomeAssistant, token: str, state: CallbackState) -> None:
    """Store callback state and remove it after its validity window."""
    states: dict[str, CallbackState] = hass.data[DOMAIN][DATA_CALLBACK_STATES]
    states[token] = state

    def expire_state(_: datetime) -> None:
        states.pop(token, None)

    async_call_later(hass, CALLBACK_TTL, expire_state)

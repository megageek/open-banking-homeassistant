"""Constants for the Open Banking integration."""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "open_banking"
LOGGER = logging.getLogger(__package__)

CONF_SECRET_ID = "secret_id"
CONF_SECRET_KEY = "secret_key"
CONF_ACCOUNT_HOLDER = "account_holder"
CONF_COUNTRY = "country"
CONF_INSTITUTION_ID = "institution_id"
CONF_INSTITUTION_NAME = "institution_name"
CONF_REQUISITION_ID = "requisition_id"
CONF_REFERENCE = "reference"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_BALANCE_TYPES = "balance_types"
CONF_RECONNECT = "reconnect"

SUBENTRY_TYPE_INSTITUTION = "institution"
DATA_CALLBACK_STATES = "callback_states"
CALLBACK_PATH = "/api/open_banking/callback"
CALLBACK_TTL = timedelta(minutes=30)

DEFAULT_REFRESH_INTERVAL = 240
MIN_REFRESH_INTERVAL = 60
MAX_REFRESH_INTERVAL = 1440

REQUISITION_LINKED = "LN"
REQUISITION_FAILED = {"EX", "RJ", "SU"}
REQUISITION_STATUSES = ["CR", "GC", "UA", "RJ", "SA", "GA", "LN", "EX", "SU"]

DEFAULT_BALANCE_TYPES = [
    "closingBooked",
    "expected",
    "forwardAvailable",
    "interimAvailable",
    "interimBooked",
    "nonInvoiced",
    "openingBooked",
]

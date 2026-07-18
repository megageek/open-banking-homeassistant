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
# Retained for callers that still reference the former setting key.
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_REFRESHES_PER_DAY = "refreshes_per_day"
CONF_REFRESH_WINDOW_START = "refresh_window_start"
CONF_REFRESH_WINDOW_END = "refresh_window_end"
CONF_BALANCE_TYPES = "balance_types"
CONF_RECONNECT = "reconnect"

SUBENTRY_TYPE_INSTITUTION = "institution"
DATA_CALLBACK_STATES = "callback_states"
CALLBACK_PATH = "/api/open_banking/callback"
CALLBACK_TTL = timedelta(minutes=30)
REQUISITION_EXPIRY_WARNING = timedelta(days=7)
REQUISITION_EXPIRY_ISSUE_PREFIX = "requisition_expiry"

DEFAULT_REFRESHES_PER_DAY = 4
DEFAULT_REFRESH_WINDOW_START = "07:00:00"
DEFAULT_REFRESH_WINDOW_END = "22:00:00"
MIN_REFRESHES_PER_DAY = 1
MAX_REFRESHES_PER_DAY = 24
MISSING_ENTITY_REFRESH_THRESHOLD = 3

REQUISITION_LINKED = "LN"
REQUISITION_FAILED = {"EX", "RJ", "SU"}
REQUISITION_STATUSES = ["cr", "gc", "ua", "rj", "sa", "ga", "ln", "ex", "su"]
SANDBOX_INSTITUTION_ID = "SANDBOXFINANCE_SFIN0000"
SANDBOX_INSTITUTION_NAME = "Sandbox Finance"

DEFAULT_BALANCE_TYPES = [
    "closingBooked",
    "expected",
    "forwardAvailable",
    "interimAvailable",
    "interimBooked",
    "nonInvoiced",
    "openingBooked",
]

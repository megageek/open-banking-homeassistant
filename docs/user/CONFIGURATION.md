# Configuration

The integration is configured exclusively through the Home Assistant UI. YAML
configuration is not supported.

## GoCardless account

The parent integration entry stores the GoCardless `secret_id` and `secret_key`.
Credentials are validated before the entry is created and can be updated with
the integration's reauthentication or reconfiguration flow.

## Bank connections

Each bank connection stores its country, institution, account-holder label,
GoCardless requisition, selected balance types, daily refresh count, and active
refresh window.

The account-holder label is used only to identify the connection in Home
Assistant. Enter a short name such as `Alex`, `Household`, or `Business`; it does
not need to match the legal name held by the bank.

Countries are shown with both their names and two-letter country codes. The
country controls which institutions are offered on the next screen.

## Refresh schedule

**Refreshes per day** controls how many scheduled data refreshes the integration
attempts each day. The supported range is 1–24 and the default is 4. Scheduled
refreshes are distributed evenly between the active-window start and end times,
which default to 07:00 and 22:00 in Home Assistant's local time zone. For
example, four refreshes use the start, two evenly spaced intermediate slots, and
the end of the window.

The integration reads rate-limit information returned by the bank and reduces
the effective schedule or waits for a reset when necessary. A bank connection's
**Last refresh** and **Next refresh** diagnostic sensors show the observed and
scheduled timestamps.

## Balance types

Balance types describe the different views of a balance that a bank may return,
such as booked, available, expected, or opening balances. The selection controls
which balance sensors Home Assistant creates; it does not change or request a
different bank account. A sensor is created only when the bank actually returns
the selected type, so selecting a type unsupported by the bank has no effect.

Reconfigure a bank connection to change its label, balance types, refresh count,
or active window. Enable **Reconnect bank authorization** when its requisition
expires or access is revoked.

## External URL

Bank authorization requires a Home Assistant external URL. Configure this in
Home Assistant before adding or reconnecting a bank. The URL must be reachable
by the browser completing the bank authorization; a local-only development URL
normally cannot complete this callback. Callback state is random, single-use,
and expires after 30 minutes.

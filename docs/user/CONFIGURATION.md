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

## Transactions

Transaction support is configured independently for each bank connection:

- **Disabled** makes no transaction requests and creates no transaction summary
  sensors. This is the default.
- **Memory only** keeps up to 90 days of transactions in memory. The raw cache is
  lost when Home Assistant restarts.
- **Encrypted persistent** encrypts the same cache and stores it in Home
  Assistant's `.storage` directory so it can be restored after restart.

Persistent caches use AES-GCM with a key derived from the configured GoCardless
secret. This makes a transaction-cache file difficult to read by itself, but it
does not protect against someone who obtains the complete Home Assistant
configuration and its credentials. Changing credentials may invalidate the
cache; the integration then discards and rebuilds it safely.

When enabled, each account provides spending today, income today, spending this
month, income this month, pending outgoing, pending outgoing today, and pending
outgoing this month sensors. "Today" follows Home Assistant's local calendar
date. "This month" is calendar month-to-date and includes today. Pending
transactions without a booking or value date are included only in the overall
pending outgoing sensor because they cannot be assigned reliably to a calendar
period. Home Assistant Recorder may store these sensor states in either enabled
mode. Responses from transaction actions may also be retained in automation or
script traces.

Transactions refresh on the bank connection's normal schedule and use a
separate bank API quota. Up to 90 days and 5,000 records per account are kept.

Each transaction-enabled account also has a **Transaction updates** event
entity. It emits `transactions_updated` when the cached transaction contents
change. The first successful fetch without an existing cache emits an initial
update, but its added, updated, and removed counts are all zero so retained
history is not presented as newly observed activity. Identical refreshes and
failed transaction requests emit nothing.

The event exposes only its cache timestamp, whether it is the initial
population, aggregate booked and pending change counts, and a
currency-mismatch count. It never includes account identifiers, transaction
identifiers, dates, currencies, amounts, descriptions, counterparties, or raw
bank data.

Home Assistant's automation editor provides native triggers for any transaction
update, newly booked transactions, and pending transaction changes. The generic
**Event received** trigger can also target the event entity. To use transaction
details in an automation, call `open_banking.get_transactions` after the trigger;
this keeps sensitive financial data out of event states and trigger variables.

## External URL

Bank authorization requires a Home Assistant external URL. Configure this in
Home Assistant before adding or reconnecting a bank. The URL must be reachable
by the browser completing the bank authorization; a local-only development URL
normally cannot complete this callback. Callback state is random, single-use,
and expires after 30 minutes.

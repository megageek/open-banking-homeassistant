# Configuration

The integration is configured exclusively through the Home Assistant UI. YAML
configuration is not supported.

## GoCardless account

The parent integration entry stores the GoCardless `secret_id` and `secret_key`.
Credentials are validated before the entry is created and can be updated with
the integration's reauthentication or reconfiguration flow.

## Bank connections

Each bank connection stores its country, institution, account-holder label,
GoCardless requisition, selected balance types, and polling interval. The
default interval is 240 minutes and the supported range is 60–1440 minutes.

Reconfigure a bank connection to change its label, balance types, or interval.
Enable **Reconnect bank authorization** when its requisition expires or access
is revoked.

## External URL

Bank authorization requires a Home Assistant external URL. Configure this in
Home Assistant before adding or reconnecting a bank. Callback state is random,
single-use, and expires after 30 minutes.

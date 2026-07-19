# Getting started

The integration is available only for banks in the supported European countries
offered by GoCardless Bank Account Data. Banks in the United States and other
regions are not supported, and not every European country is available. The
country selector during setup shows the complete supported list.

GoCardless no longer accepts new registrations for the Bank Account Data
service. This integration therefore works only for people who already have a
Bank Account Data account. A standard GoCardless payments account is not a
substitute.

## Create credentials for an existing account

1. [Sign in to your existing Bank Account Data account](https://auth0.gocardless.com/login).
2. Open the portal's
   [**User Secrets** page](https://bankaccountdata.gocardless.com/user-secrets/).
3. Select **Create new user secrets**.
4. Securely copy the generated **Secret ID** and **Secret key**. Home Assistant
   requests both values when the integration is added.

The secret pair authorizes access to every bank connection created under that
GoCardless account. Treat both values like passwords: do not publish them, add
them to source control, or include them in support messages. They are GoCardless
API credentials and are separate from the credentials used to sign in to your
bank.

## Install and connect

Configure a public external URL in Home Assistant, then install the integration
through HACS or by copying `custom_components/open_banking` into the Home
Assistant configuration.

After restarting, add **Open Banking via GoCardless** from **Settings → Devices &
services**. Enter the user secrets, select the connection label, country,
balance types, refresh schedule, and transaction-storage mode, then select an
institution and complete authorization at the bank. The callback returns to
Home Assistant and creates the bank connection automatically.

The account-holder label is simply a name for identifying the connection in
Home Assistant, such as a person's name or `Household`; it is not submitted to
the bank as a legal account-holder name. Country choices include both the
country name and code.

Each GoCardless credential pair is one integration entry. Further institutions
are added as bank connections beneath that entry, so credentials are stored only
once.

Each connection defaults to four scheduled refreshes per day, spread evenly
between 07:00 and 22:00 local time. You can change the daily count, active
window, and desired balance types during setup or by reconfiguring the bank
connection later.

Transaction support is disabled by default. **Memory only** keeps a 90-day raw
cache until Home Assistant restarts. **Encrypted persistent** stores an
encrypted cache in Home Assistant's `.storage` directory and displays a privacy
warning before it is enabled. Both enabled modes create transaction summary
sensors and transaction-update event entities. Review the
[configuration guide](CONFIGURATION.md#transactions) before selecting a mode.

# Getting started

Create GoCardless Bank Account Data user secrets, configure a public external
URL in Home Assistant, and install the integration through HACS or by copying
`custom_components/open_banking` into the Home Assistant configuration.

After restarting, add **Open Banking via GoCardless** from **Settings → Devices &
services**. Enter the user secrets, select the account holder label, country,
and institution, then complete authorization at the bank. The callback returns
to Home Assistant and creates the bank connection automatically.

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

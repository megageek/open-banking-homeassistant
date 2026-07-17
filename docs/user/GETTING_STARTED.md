# Getting started

Create GoCardless Bank Account Data user secrets, configure a public external
URL in Home Assistant, and install the integration through HACS or by copying
`custom_components/open_banking` into the Home Assistant configuration.

After restarting, add **Open Banking (GoCardless)** from **Settings → Devices &
services**. Enter the user secrets, select the account holder label, country,
and institution, then complete authorization at the bank. The callback returns
to Home Assistant and creates the bank connection automatically.

Each GoCardless credential pair is one integration entry. Further institutions
are added as bank connections beneath that entry, so credentials are stored only
once.

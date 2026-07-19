# Examples

## Combined balance template

Balance sensor names depend on the bank account and balance types returned by
the API. After setup, select the entity IDs from **Developer tools → States**.

```yaml
template:
  - sensor:
      - name: "Combined available balance"
        unit_of_measurement: "GBP"
        state: >-
          {{
            states('sensor.current_account_interim_available_balance') | float(0)
            + states('sensor.savings_interim_available_balance') | float(0)
          }}
```

Only combine accounts that use the same currency.

## Refresh timestamps

Each bank connection provides **Last refresh** and **Next refresh** timestamp
sensors. They can be used in dashboards and automations just like other Home
Assistant timestamp sensors. The next-refresh value follows the configured
daily schedule and may move later when a bank reports that its rate limit has
been exhausted.

## Retrieve cached transactions

The `open_banking.get_transactions` action returns normalized cached
transactions without making a new bank API request. Select an account device;
the default response contains up to 100 booked and pending transactions from the
previous 30 local calendar days, ordered newest first. Optional `date_from` and
`date_to` filters must remain within the retained 90-day window, and `limit`
accepts values from 1 to 500.

```yaml
action: open_banking.get_transactions
data:
  device_id: ACCOUNT_DEVICE_ID
  status: booked
  limit: 50
response_variable: recent_transactions
```

Each normalized transaction contains its normalized ID, booked or pending
status, booking and value dates when supplied, amount, currency, counterparty,
and description. The top-level response identifies the selected account device,
display name, currency, cache timestamp, requested range, and whether the result
was truncated.

Set `include_raw: true` only when the normalized fields are insufficient. Raw
bank objects vary between institutions, may be large and cryptic, contain
sensitive information, and may be retained in automation traces.

## React to transaction updates

The automation editor offers native Open Banking triggers for transaction
updates, new booked transactions, and pending changes. Trigger variables contain
only timestamps and aggregate change counts. Call the cached transaction action
when the automation explicitly needs transaction details:

```yaml
triggers:
  - trigger: open_banking.new_booked_transactions
    target:
      entity_id: event.main_account_transaction_updates
actions:
  - action: open_banking.get_transactions
    data:
      device_id: ACCOUNT_DEVICE_ID
      status: booked
      limit: 20
    response_variable: recent_booked_transactions
```

The first cache population fires only the general transaction-updated trigger.
It does not fire the new-booked or pending-change triggers for retained history.

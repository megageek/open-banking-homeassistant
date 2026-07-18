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
last 30 days.

```yaml
action: open_banking.get_transactions
data:
  device_id: ACCOUNT_DEVICE_ID
  status: booked
  limit: 50
response_variable: recent_transactions
```

Set `include_raw: true` only when the normalized fields are insufficient. Raw
bank objects vary between institutions, may be large and cryptic, contain
sensitive information, and may be retained in automation traces.

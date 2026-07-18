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

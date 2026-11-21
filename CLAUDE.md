# chargeahead-prices

Public per-operator EV charging prices that the ChargeAhead backend reads
every 10 minutes (`PRICE_TABLES_URL`), one file per country: `tr.json`.
Everything here is public: put nothing in this repo you wouldn't publish.

## What a row is

```json
{"name": "ZES", "keys": ["Zorlu Energy Solutions"], "ac": 10.99, "dc": [12.99, 16.49],
 "source": "https://zes.net/tr/fiyatlandirma", "check": "page",
 "checked": "2026-11-21", "changed": "2026-11-05", "note": "…"}
```

- `ac`, `dc`: per kWh, VAT included, in the file's `currency`; a number, a
  `[min, max]` range, or `null` when not offered or not known.
- `keys`: other spellings of the brand in station data, so the backend
  matches a station to its operator.
- `check`: `page` when the price is on the operator's own website, `app`
  when only its app shows it (Sami checks those by hand).
- `checked`: the day the price was last seen to be current; `changed`: the
  day it last changed. The app shows "as of <checked>", greys a price
  after 30 days and the backend drops it after 60.

## Rules

- Prices come from each operator's **own** public page or app. Never copy
  from comparison sites or news: their compiled tables are their work.
- Every change goes through a pull request that Sami merges. Routines and
  sessions never merge and never push to `main`.
- `python3 prices.py validate` must pass (CI runs it on every pull request).
- Slack: only **#charger-prices**, through the Slack connector; no DMs, no
  reactions.
- The weekly check is the `prices-check` skill.

## Turkey

The Şarj Hizmeti Yönetmeliği (amended 23 Mar 2026, art. 25) allows one AC
and one DC price per kWh per operator, without session or connection fees;
discounts by place and time are allowed (hence ranges). Operators must
publish their prices on their website, in their app and at the station.

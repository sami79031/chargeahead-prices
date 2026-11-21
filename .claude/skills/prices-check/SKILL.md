---
name: prices-check
description: Weekly check of ChargeAhead's per-operator charging prices (tr.json and any other <cc>.json). Reads each operator's own pricing page, updates prices and check dates on a branch, opens one pull request for Sami to merge, and posts a summary to Slack #charger-prices. Use when asked to "check prices", "run the weekly price check", or by the prices-check routine.
---

# prices-check

Read `CLAUDE.md` first. You propose; Sami approves by merging the pull
request. Never merge, never push to `main`.

## 1. Start a branch

```bash
git fetch -q origin
git switch -c prices/$(date +%Y-%m-%d) origin/main
```

If a `prices/*` pull request is already open (`gh api repos/sami79031/chargeahead-prices/pulls`),
add to its branch instead of opening a second one.

## 2. Check every operator

For each row in each `<cc>.json`:

- **`check: page`**: fetch `source` (WebFetch). Read the per-kWh price, VAT
  included (KDV dahil), for AC and for DC. A range (discounts by place or
  time) is `[min, max]`.
  - Same as the row: set `checked` to today.
  - Different: set the new `ac`/`dc`, `changed` and `checked` to today, and
    quote the page's text in the pull request.
  - Page unreadable, or the numbers unclear (members only, excl. VAT, a
    campaign): leave the row as it is and list it under "Check by hand".
- **`check: app`**: the price is only in the operator's app. Leave the row
  and list it under "Check by hand" with its `source`.

Only the operator's own pages count. Comparison sites and news (araclo.com,
karekod.org, tamindir, newspapers) may only tell you to look again at an
operator's own page: never copy a price from them.

New operator found on an operator's own site or in drivers' reports? Add a
row with `check: page` or `app`, its `source`, and its brand's other
spellings in `keys` (how station data writes the brand: "Zorlu Energy
Solutions" for ZES).

## 3. Validate and summarise

```bash
python3 prices.py validate
python3 prices.py summary origin/main
```

Fix every problem `validate` reports.

## 4. Open the pull request

Commit only the `<cc>.json` files you changed, push the branch, and open
the pull request with `gh api`:

- Title: `Prices <date>: <n> changed` (or `Prices <date>: no changes`).
- Body: the `summary` lines; for each change, the page text you read;
  then "Check by hand" with each operator, its `source` and why.

## 5. Tell Sami in Slack

Post one message to **#charger-prices** with the Slack connector:

- the summary lines (or "No price changes"),
- the pull request link ("merge to publish; the app picks it up within 10
  minutes"),
- the "Check by hand" list: Sami opens each app, and replies with the
  prices or edits the pull request.

Never post anywhere else, never DM, never react.

## 6. Finish

Print: `prices-check: <n> rows checked, <c> changed, <h> by hand, PR <url>`.

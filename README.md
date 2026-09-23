# Meta Ads — daily brief

Pulls Facebook and Instagram ad data straight from the Meta Marketing API and
builds a dashboard out of it. No Supermetrics, no subscription, no software
running on your computer.

GitHub runs it every morning at 06:00 Lagos time. **Read [SETUP.md](SETUP.md)
first** — that is the whole install.

---

## What it produces

`public/index.html` — one self-contained page:

| Section | What it tells you |
|---|---|
| Ledger | spend per day, cost per link click, link CTR, results |
| Read this first | one verdict on the account, written from the numbers |
| 1 · Week on week | this week against the previous week, colour-coded |
| 2 · Daily trend | spend, clicks and results per day |
| 3 · Campaigns | sorted by spend, each flagged winner / watch / waste |
| 4 · Ad sets | where the targeting shows up |
| 5 · Ads | which creative is actually working |
| 6 · What to do | ranked actions, P0 to P3, generated from the data |

`data/*.csv` — the raw pull, one file per level, so the numbers can be checked
and the history builds up over time.

## The verdicts

Every campaign, ad set and ad gets a flag:

- **winner** — cost per result is inside your target
- **watch** — over target, but under 1.5×
- **waste** — more than 1.5× target, or spending with nothing to show
- **est** — fewer than 15 link clicks, too thin to judge either way

Set the targets with the `TARGET_CPC` and `TARGET_CPR` repository variables.
Get them wrong and every verdict is wrong, so start with what a reader is
actually worth to you.

---

## Running it on your own machine instead

You do not need to. But if you want to:

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in the two blanks
python meta_ads.py --days 30
python build_dashboard.py --open
```

### Puller options

```bash
python meta_ads.py --days 7                         # last 7 days
python meta_ads.py --level ad                       # ad level only
python meta_ads.py --since 2026-09-01 --until 2026-09-23
python meta_ads.py --no-daily                       # totals, not day by day
python meta_ads.py --token-info                     # how long the token has left
python meta_ads.py --exchange-token                 # short token -> 60-day token
```

### Dashboard options

```bash
python build_dashboard.py --target-cpc 0.30 --target-cpr 1.50 --currency AUD
python build_dashboard.py --out public/index.html
```

---

## Notes

- The pull stops at yesterday. Today's figures are not final and Meta keeps
  filling conversions in for 24–72 hours after the fact.
- A brand-new campaign returns **0 rows**. That is not a bug — it has not
  served yet.
- Meta's learning phase is 3–7 days or 50 results. Numbers before that swing
  hard. Do not turn things off on day one.
- Meta raises the API version a few times a year. If a field breaks, set the
  `META_API_VERSION` repository variable to a newer version, e.g. `v24.0`.
- The access token lasts 60 days. The daily job opens an issue when it is
  nearly out; SETUP.md step "Every ~55 days" has the fix.

## Columns in the CSVs

date, campaign / ad set / ad names and IDs, impressions, reach, frequency,
clicks, link clicks, CTR, link CTR, CPC, CPM, spend — plus flattened action
columns: `act_link_click`, `act_landing_page_view`, `act_post_engagement`,
`act_like`, `act_purchase`, with matching `val_*` (value) and `cost_*`
(cost per action) columns.

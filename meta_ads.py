#!/usr/bin/env python3
"""
Meta (Facebook/Instagram) Ads data puller.
Free replacement for Supermetrics. Pulls insights -> CSV.

Usage:
    python meta_ads.py                      # last 30 days, all levels
    python meta_ads.py --days 7             # last 7 days
    python meta_ads.py --level ad           # just ad level
    python meta_ads.py --since 2026-09-01 --until 2026-09-23
    python meta_ads.py --exchange-token     # short token -> 60-day token
"""

import argparse
import csv
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------- config

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

APP_ID = os.getenv("META_APP_ID", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "").strip()
API_VERSION = os.getenv("META_API_VERSION", "v23.0").strip()

BASE = f"https://graph.facebook.com/{API_VERSION}"
OUT_DIR = ROOT / "data"

# Metrics pulled for every row.
FIELDS = [
    "date_start",
    "date_stop",
    "account_name",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "objective",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "inline_link_clicks",
    "ctr",
    "inline_link_click_ctr",
    "cpc",
    "cpm",
    "spend",
    "actions",
    "action_values",
    "cost_per_action_type",
]

# Action types flattened into their own columns.
ACTION_COLUMNS = [
    "link_click",
    "landing_page_view",
    "post_engagement",
    "page_engagement",
    "like",
    "post_reaction",
    "comment",
    "onsite_conversion.post_save",
    "video_view",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
]


# ---------------------------------------------------------------- helpers

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_config():
    missing = []
    if not TOKEN:
        missing.append("META_ACCESS_TOKEN")
    if not ACCOUNT_ID:
        missing.append("META_AD_ACCOUNT_ID")
    if missing:
        die(f"Missing in .env: {', '.join(missing)}. Copy .env.example to .env and fill it in.")


def account_path():
    acct = ACCOUNT_ID if ACCOUNT_ID.startswith("act_") else f"act_{ACCOUNT_ID}"
    return acct


def get(url, params, tries=5):
    """GET with retry on rate limit / transient errors."""
    for attempt in range(tries):
        r = requests.get(url, params=params, timeout=90)
        if r.status_code == 200:
            return r.json()

        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {"message": r.text[:300]}

        code = err.get("code")
        msg = err.get("message", "")

        # 4 = app rate limit, 17 = user rate limit, 613 = calls exceeded, 2 = transient
        if code in (4, 17, 613, 2) or r.status_code >= 500:
            wait = 2 ** attempt * 15
            print(f"  rate limited / transient ({code}). waiting {wait}s...")
            time.sleep(wait)
            continue

        if code == 190:
            die(f"Token invalid or expired. Regenerate it. Meta said: {msg}")

        if code == 100 and "nonexisting field" in msg.lower():
            die(f"Bad field for this API version. Meta said: {msg}")

        die(f"API error {code}: {msg}")

    die("Gave up after repeated rate limits. Try again in an hour.")


def paginate(url, params):
    """Yield every row across all pages."""
    rows = []
    page = 1
    while True:
        payload = get(url, params)
        batch = payload.get("data", [])
        rows.extend(batch)
        print(f"  page {page}: {len(batch)} rows (total {len(rows)})")

        nxt = payload.get("paging", {}).get("next")
        if not nxt or not batch:
            break
        # next URL already carries the cursor + params
        url, params, page = nxt, None, page + 1
        time.sleep(1)
    return rows


# ---------------------------------------------------------------- token

def exchange_token():
    """Swap a short-lived token for a ~60-day one."""
    if not APP_ID or not APP_SECRET:
        die("Set META_APP_ID and META_APP_SECRET in .env first.")
    if not TOKEN:
        die("Put your short-lived token in META_ACCESS_TOKEN first.")

    r = requests.get(
        f"{BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "fb_exchange_token": TOKEN,
        },
        timeout=60,
    )
    data = r.json()
    if "access_token" not in data:
        die(f"Exchange failed: {data}")

    new_token = data["access_token"]
    expires = data.get("expires_in")
    days = round(expires / 86400) if expires else "~60"

    print("\nLong-lived token (valid ~%s days):\n" % days)
    print(new_token)
    print("\nPaste it into .env as META_ACCESS_TOKEN, replacing the old one.")
    print("Set a reminder to re-run this before it expires.\n")


def token_info():
    """Show when the current token expires."""
    if not APP_ID or not APP_SECRET:
        die("Set META_APP_ID and META_APP_SECRET in .env to inspect the token.")
    data = get(
        f"{BASE}/debug_token",
        {"input_token": TOKEN, "access_token": f"{APP_ID}|{APP_SECRET}"},
    ).get("data", {})

    exp = data.get("expires_at", 0)
    left = None
    if exp == 0:
        print("Token does not expire.")
    else:
        left = (exp - time.time()) / 86400
        print(f"Token expires in {left:.1f} days.")
    print("Scopes:", ", ".join(data.get("scopes", [])))
    print("Valid:", data.get("is_valid"))

    # Write a machine-readable line for GitHub Actions to pick up.
    gh_out = os.getenv("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"days_left={left if left is not None else 9999:.0f}\n")

    if left is not None and left < 7:
        print(f"::warning::Meta token expires in {left:.0f} days. "
              f"Run the refresh-token workflow and update the META_ACCESS_TOKEN secret.")


# ---------------------------------------------------------------- pull

def flatten_actions(row):
    """Turn the nested actions / values arrays into flat columns."""
    out = {}

    for item in row.get("actions") or []:
        t = item.get("action_type")
        if t in ACTION_COLUMNS:
            out[f"act_{t}"] = item.get("value")

    for item in row.get("action_values") or []:
        t = item.get("action_type")
        if t in ACTION_COLUMNS:
            out[f"val_{t}"] = item.get("value")

    for item in row.get("cost_per_action_type") or []:
        t = item.get("action_type")
        if t in ACTION_COLUMNS:
            out[f"cost_{t}"] = item.get("value")

    return out


def pull(level, since, until, daily=True):
    print(f"\nPulling {level}-level insights, {since} to {until}...")

    params = {
        "access_token": TOKEN,
        "level": level,
        "fields": ",".join(FIELDS),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "limit": 500,
        "action_report_time": "conversion",
        "use_unified_attribution_setting": "true",
    }
    if daily:
        params["time_increment"] = 1

    raw = paginate(f"{BASE}/{account_path()}/insights", params)

    rows = []
    for r in raw:
        flat = {k: v for k, v in r.items()
                if k not in ("actions", "action_values", "cost_per_action_type")}
        flat.update(flatten_actions(r))
        rows.append(flat)

    return rows


def write_csv(rows, path):
    if not rows:
        print(f"  no rows -> skipping {path.name}")
        return

    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"  wrote {len(rows)} rows -> {path}")


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Pull Meta Ads data to CSV.")
    p.add_argument("--days", type=int, default=30, help="lookback window (default 30)")
    p.add_argument("--since", help="start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--until", help="end date YYYY-MM-DD")
    p.add_argument("--level", choices=["account", "campaign", "adset", "ad", "all"],
                   default="all", help="report level (default all)")
    p.add_argument("--no-daily", action="store_true",
                   help="one summary row per entity instead of one per day")
    p.add_argument("--exchange-token", action="store_true",
                   help="swap short token for 60-day token and exit")
    p.add_argument("--token-info", action="store_true",
                   help="show token expiry and scopes, then exit")
    args = p.parse_args()

    if args.exchange_token:
        exchange_token()
        return

    check_config()

    if args.token_info:
        token_info()
        return

    until = args.until or (date.today() - timedelta(days=1)).isoformat()
    since = args.since or (date.fromisoformat(until) - timedelta(days=args.days - 1)).isoformat()

    levels = ["campaign", "adset", "ad"] if args.level == "all" else [args.level]
    stamp = date.today().isoformat()

    for lvl in levels:
        rows = pull(lvl, since, until, daily=not args.no_daily)
        write_csv(rows, OUT_DIR / f"meta_{lvl}_{since}_to_{until}.csv")
        # also keep a stable "latest" file for the dashboard to read
        write_csv(rows, OUT_DIR / f"meta_{lvl}_latest.csv")
        time.sleep(2)

    print(f"\nDone. Files in {OUT_DIR}  ({stamp})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Build The Morning Brief — Meta Ads.

Reads the CSVs written by meta_ads.py and writes a single self-contained
HTML page: dashboard.html

Usage:
    python build_dashboard.py
    python build_dashboard.py --target-cpc 0.30 --target-cpr 2.00
    python build_dashboard.py --currency USD
    python build_dashboard.py --open          # also open it in the browser
"""

import argparse
import csv
import html
import math
import os
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "dashboard.html"

# ---------------------------------------------------------------- defaults
# Override any of these from the command line.
DEFAULTS = {
    "target_cpc": 0.35,       # what you want to pay per link click
    "target_cpr": 2.00,       # what you want to pay per result (follow / LPV / purchase)
    "min_clicks": 15,         # below this, a row is "not enough data to judge"
    "min_impr": 500,          # below this, CTR is noise
    "currency": "USD",
}

CUR = {"USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "CAD": "C$", "NGN": "₦"}


# ---------------------------------------------------------------- loading

def load(level):
    """Read meta_<level>_latest.csv into a list of dicts. Missing file = []."""
    p = DATA / f"meta_{level}_latest.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(row, key, default=0.0):
    v = row.get(key)
    if v in (None, "", "None"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pick_result_column(rows):
    """
    Decide what 'a result' means for this account, by looking at what
    actually has values. Ordered most-valuable first.
    """
    candidates = [
        ("act_offsite_conversion.fb_pixel_purchase", "Purchases"),
        ("act_purchase", "Purchases"),
        ("act_landing_page_view", "Landing page views"),
        ("act_link_click", "Link clicks"),
        ("act_like", "Page likes"),
        ("act_post_engagement", "Post engagements"),
        ("act_page_engagement", "Page engagements"),
        ("act_video_view", "Video views"),
    ]
    for col, label in candidates:
        if any(num(r, col) > 0 for r in rows):
            return col, label
    return None, "Results"


# ---------------------------------------------------------------- math

def agg(rows):
    """Sum a set of rows into one totals dict with derived metrics."""
    t = {
        "spend": sum(num(r, "spend") for r in rows),
        "impressions": sum(num(r, "impressions") for r in rows),
        "reach": sum(num(r, "reach") for r in rows),
        "clicks": sum(num(r, "clicks") for r in rows),
        "link_clicks": sum(num(r, "inline_link_clicks") for r in rows),
        "results": 0.0,
        "days": len({r.get("date_start") for r in rows if r.get("date_start")}),
    }
    t["ctr"] = pct(t["clicks"], t["impressions"])
    t["link_ctr"] = pct(t["link_clicks"], t["impressions"])
    t["cpc"] = div(t["spend"], t["link_clicks"])
    t["cpc_all"] = div(t["spend"], t["clicks"])
    t["cpm"] = div(t["spend"], t["impressions"]) * 1000
    t["freq"] = div(t["impressions"], t["reach"])
    return t


def add_results(t, rows, col):
    t["results"] = sum(num(r, col) for r in rows) if col else 0.0
    t["cpr"] = div(t["spend"], t["results"])
    return t


def div(a, b):
    return a / b if b else 0.0


def pct(a, b):
    return (a / b * 100) if b else 0.0


def delta(new, old):
    """Percent change, or None when there's no base to compare against."""
    if not old:
        return None
    return (new - old) / old * 100


# ---------------------------------------------------------------- format

def fmt_money(v, sym, dp=2):
    return f"{sym}{v:,.{dp}f}"


def fmt_int(v):
    return f"{v:,.0f}"


def fmt_pct(v, dp=2):
    return f"{v:.{dp}f}%"


def dx(d, good_when_down=False, dp=0):
    """Coloured change chip. good_when_down=True for costs."""
    if d is None:
        return '<span class="dx slate">n/a</span>'
    up = d >= 0
    good = (not up) if good_when_down else up
    cls = "green" if good else "red"
    if abs(d) < 1:
        cls = "gold"
    sign = "+" if up else "−"
    return f'<span class="dx {cls}">{sign}{abs(d):.{dp}f}%</span>'


def esc(s):
    return html.escape(str(s if s is not None else ""))


# ---------------------------------------------------------------- verdicts

def judge(row_t, cfg):
    """
    Return (flag, tag, reason) for one campaign / adset / ad.
    flag: green | gold | red | slate   tag: winner | watch | waste | est
    """
    sym = CUR.get(cfg["currency"], "$")

    if row_t["spend"] == 0:
        return "slate", "est", "No spend in this window."

    if row_t["link_clicks"] < cfg["min_clicks"] and row_t["results"] < cfg["min_clicks"]:
        return ("slate", "est",
                f"Only {fmt_int(row_t['link_clicks'])} link clicks — under {cfg['min_clicks']}, "
                f"too thin to call either way.")

    # Cost per result is the real test when results exist.
    if row_t["results"] > 0:
        cpr = row_t["cpr"]
        if cpr <= cfg["target_cpr"] * 0.75:
            return "green", "winner", f"{fmt_money(cpr, sym)} per result vs {fmt_money(cfg['target_cpr'], sym)} target."
        if cpr <= cfg["target_cpr"]:
            return "green", "winner", f"{fmt_money(cpr, sym)} per result, inside target."
        if cpr <= cfg["target_cpr"] * 1.5:
            return "gold", "watch", f"{fmt_money(cpr, sym)} per result vs {fmt_money(cfg['target_cpr'], sym)} target — over, not wildly."
        return "red", "waste", f"{fmt_money(cpr, sym)} per result — {cpr / cfg['target_cpr']:.1f}× your target."

    # No results at all: fall back to cost per link click.
    cpc = row_t["cpc"]
    if cpc == 0:
        return "red", "waste", f"{fmt_money(row_t['spend'], sym)} spent, zero link clicks."
    if cpc <= cfg["target_cpc"]:
        return "gold", "watch", f"{fmt_money(cpc, sym)} per click is fine, but no results are landing yet."
    return "red", "waste", f"{fmt_money(cpc, sym)} per click and no results — {cpc / cfg['target_cpc']:.1f}× your click target."


# ---------------------------------------------------------------- chart bits

def hbar(label, value, maxv, display, cls=""):
    w = 0 if not maxv else min(100, value / maxv * 100)
    return (f'<div class="hrow"><div class="lbl">{esc(label)}</div>'
            f'<div class="track"><div class="fill {cls}" style="width:{w:.1f}%"></div></div>'
            f'<div class="val">{display}</div></div>')


def columns(series, labels, highlight_from=None, unit=""):
    """series: list of floats. Returns the column chart HTML."""
    if not series:
        return '<div class="na">No daily data yet.</div>'
    mx = max(series) or 1
    avg = sum(series) / len(series)
    bars = []
    for i, v in enumerate(series):
        h = max(2, v / mx * 100)
        cls = "post" if (highlight_from is not None and i >= highlight_from) else "pre"
        title = f"{labels[i]}: {v:,.2f}{unit}" if i < len(labels) else f"{v:,.2f}{unit}"
        bars.append(f'<div class="c {cls}" style="height:{h:.1f}%" title="{esc(title)}"></div>')
    avg_top = 100 - (avg / mx * 100)
    first = labels[0] if labels else ""
    last = labels[-1] if labels else ""
    return (f'<div class="cols">{"".join(bars)}'
            f'<div class="avg" style="top:{avg_top:.1f}%"><span>avg {avg:,.2f}{unit}</span></div></div>'
            f'<div class="colaxis"><span>{esc(first)}</span><span>{esc(last)}</span></div>')


# ---------------------------------------------------------------- page

CSS = """
:root {
  --ink:#16243D; --paper:#F6F3EC; --paper-raised:#FDFCF8; --line:#D9D3C4; --line-strong:#B7AF9B;
  --gold:#9A6A17; --green:#2C6B4B; --green-bg:#E8EFE7; --red:#A23B2E; --red-bg:#F5E7E3;
  --amber-bg:#F3ECDA; --slate:#5B6472; --text:#201C15; --bar:#5E6E8C; --bar-soft:#C9CFDB;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ink:#EDE7D8; --paper:#14120F; --paper-raised:#1C1913; --line:#3A362C; --line-strong:#504A3C;
    --gold:#D3A24C; --green:#6FAE8B; --green-bg:#1C2A22; --red:#E08573; --red-bg:#2E1F1C;
    --amber-bg:#2A2316; --slate:#A79F8C; --text:#EDE7D8; --bar:#9FB0CF; --bar-soft:#3B4252;
  }
}
:root[data-theme="dark"] {
  --ink:#EDE7D8; --paper:#14120F; --paper-raised:#1C1913; --line:#3A362C; --line-strong:#504A3C;
  --gold:#D3A24C; --green:#6FAE8B; --green-bg:#1C2A22; --red:#E08573; --red-bg:#2E1F1C;
  --amber-bg:#2A2316; --slate:#A79F8C; --text:#EDE7D8; --bar:#9FB0CF; --bar-soft:#3B4252;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--text);
  font-family:'IBM Plex Sans',system-ui,-apple-system,sans-serif; font-size:16px; line-height:1.5; }
.wrap { max-width:980px; margin:0 auto; padding:0 24px 80px; }
@media (max-width:640px){ .wrap{ padding:0 16px 60px; } }

.masthead { padding:48px 8px 28px; border-bottom:3px solid var(--ink); text-align:center; }
.kicker { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:13px; letter-spacing:.04em; color:var(--slate); margin-bottom:10px; }
.masthead h1 { font-family:'Source Serif 4',Georgia,serif; font-weight:700; font-size:clamp(1.7rem,4.4vw,2.6rem);
  margin:0 0 8px; color:var(--ink); letter-spacing:-.01em; text-wrap:balance; }
.dateline { font-size:14px; color:var(--slate); }
.dateline strong { color:var(--text); }
.toc { display:flex; flex-wrap:wrap; justify-content:center; gap:6px 16px; margin-top:16px; font-size:13px; }
.toc a { color:var(--slate); text-decoration:none; border-bottom:1px solid var(--line-strong); }
.toc a:hover,.toc a:focus-visible { color:var(--ink); border-color:var(--ink); outline:none; }

.ledger { display:grid; grid-template-columns:repeat(4,1fr); border-bottom:1px solid var(--line); margin-top:8px; }
.ledger .cell { padding:22px 18px; border-left:1px solid var(--line); }
.ledger .cell:first-child { border-left:none; }
.label { font-size:12.5px; color:var(--slate); margin-bottom:6px; }
.value { font-family:'Source Serif 4',Georgia,serif; font-size:1.7rem; font-weight:600; color:var(--ink); font-variant-numeric:tabular-nums; }
.value .u { font-size:1rem; }
.sub { font-size:12.5px; color:var(--slate); margin-top:4px; }
.sub.good{color:var(--green)} .sub.warn{color:var(--gold)} .sub.bad{color:var(--red)}
@media (max-width:700px){ .ledger{grid-template-columns:repeat(2,1fr)}
  .ledger .cell:nth-child(3){border-left:none} .ledger .cell:nth-child(n+3){border-top:1px solid var(--line)} }

section { padding:44px 0; border-bottom:1px solid var(--line); scroll-margin-top:12px; }
section:last-of-type { border-bottom:none; }
.section-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:6px; }
.section-head h2 { font-family:'Source Serif 4',Georgia,serif; font-weight:600; font-size:1.5rem; margin:0; color:var(--ink); text-wrap:balance; }
.section-head .note { font-size:13px; color:var(--slate); }
.snum { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:13px; color:var(--slate); margin-right:8px; font-weight:400; }
.section-intro { color:var(--slate); font-size:14.5px; margin:4px 0 22px; max-width:66ch; }
h3 { font-family:'Source Serif 4',Georgia,serif; font-size:1.1rem; font-weight:600; color:var(--ink); margin:28px 0 10px; }

.chart-title { font-size:13px; color:var(--slate); margin-bottom:10px; }
.hrow { display:grid; grid-template-columns:200px 1fr 100px; align-items:center; gap:12px; font-size:13.5px; margin-bottom:9px; }
.hrow .lbl { color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hrow .val { text-align:right; font-family:'IBM Plex Mono',ui-monospace,monospace; font-variant-numeric:tabular-nums; }
.track { position:relative; height:12px; background:var(--line); border-radius:0 4px 4px 0; }
.fill { position:absolute; left:0; top:0; bottom:0; border-radius:0 4px 4px 0; background:var(--bar); }
.fill.green{background:var(--green)} .fill.gold{background:var(--gold)} .fill.red{background:var(--red)} .fill.soft{background:var(--bar-soft)}
@media (max-width:640px){ .hrow{grid-template-columns:120px 1fr 78px; gap:8px; font-size:12.5px} }
.two { display:grid; grid-template-columns:1fr 1fr; gap:28px 40px; }
@media (max-width:760px){ .two{grid-template-columns:1fr} }
.axis-note { font-size:11.5px; color:var(--slate); margin-top:6px; }

.cols { display:flex; align-items:flex-end; gap:2px; height:150px; border-bottom:1px solid var(--line-strong); position:relative; padding-top:4px; }
.cols .c { flex:1 1 0; background:var(--bar-soft); border-radius:2px 2px 0 0; min-width:0; }
.cols .c.post { background:var(--bar); }
.cols .c.pre { background:var(--bar-soft); }
.cols .avg { position:absolute; left:0; right:0; border-top:1px dashed var(--line-strong); }
.cols .avg span { position:absolute; right:0; top:-16px; font-size:10.5px; font-family:'IBM Plex Mono',ui-monospace,monospace;
  color:var(--slate); background:var(--paper); padding:0 3px; }
.colaxis { display:flex; justify-content:space-between; font-size:11px; color:var(--slate);
  font-family:'IBM Plex Mono',ui-monospace,monospace; margin-top:6px; }

.table-scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { text-align:left; font-weight:500; color:var(--slate); font-size:12.5px; padding:0 10px 10px 0;
  border-bottom:1px solid var(--line-strong); white-space:nowrap; }
td { padding:11px 10px 11px 0; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:none; }
td.num,th.num { text-align:right; font-family:'IBM Plex Mono',ui-monospace,monospace; font-variant-numeric:tabular-nums; white-space:nowrap; }
td .why { display:block; font-size:12.5px; color:var(--slate); margin-top:3px;
  font-family:'IBM Plex Sans',system-ui,sans-serif; white-space:normal; }
.row-flag { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:8px; position:relative; top:-1px; }
.row-flag.green{background:var(--green)} .row-flag.gold{background:var(--gold)}
.row-flag.red{background:var(--red)} .row-flag.slate{background:var(--line-strong)}
.tag,.dx { display:inline-block; font-size:11px; font-family:'IBM Plex Mono',ui-monospace,monospace;
  padding:2px 7px; border-radius:3px; white-space:nowrap; }
.tag.winner,.dx.green { background:var(--green-bg); color:var(--green); }
.tag.waste,.dx.red { background:var(--red-bg); color:var(--red); }
.tag.watch,.dx.gold { background:var(--amber-bg); color:var(--gold); }
.dx.slate,.tag.est { background:transparent; color:var(--slate); border:1px solid var(--line-strong); }
.wide-table { min-width:760px; }

.flag-box { border-left:3px solid var(--gold); background:var(--amber-bg); padding:16px 20px; margin-top:16px; font-size:14px; }
.flag-box.red { border-left-color:var(--red); background:var(--red-bg); }
.flag-box.green { border-left-color:var(--green); background:var(--green-bg); }
.flag-box strong { color:var(--ink); }

.na { border:1px dashed var(--line-strong); padding:22px; font-size:14.5px; color:var(--slate); }
.na strong { color:var(--ink); }
.na ul { margin:10px 0 0; padding-left:20px; }
.na li { margin-bottom:6px; }

.plan { display:grid; gap:0; }
.p { display:grid; grid-template-columns:56px 1fr; gap:16px; padding:18px 0; border-top:1px solid var(--line); }
.p:first-child { border-top:none; }
.pbadge { font-family:'IBM Plex Mono',ui-monospace,monospace; font-weight:500; font-size:14px; height:30px;
  display:grid; place-items:center; border-radius:3px; }
.pbadge.p0{background:var(--red-bg);color:var(--red)} .pbadge.p1{background:var(--amber-bg);color:var(--gold)}
.pbadge.p2{background:var(--green-bg);color:var(--green)} .pbadge.p3{border:1px solid var(--line-strong);color:var(--slate)}
.p h4 { margin:0 0 8px; font-size:15.5px; color:var(--ink); font-weight:600; }
.p p { margin:0; font-size:13.5px; color:var(--slate); }
.p code { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:12px; background:var(--paper-raised);
  border:1px solid var(--line); padding:1px 5px; border-radius:3px; word-break:break-word; }
@media (max-width:560px){ .p{grid-template-columns:1fr;gap:8px} .pbadge{width:48px} }

.fixfirst { display:grid; grid-template-columns:auto 1fr; gap:16px; align-items:center; margin:22px 0 0;
  padding:18px 22px; background:var(--amber-bg); border-left:4px solid var(--gold); color:var(--text); font-size:14.5px; }
.fixfirst.green { background:var(--green-bg); border-left-color:var(--green); }
.fixfirst.red { background:var(--red-bg); border-left-color:var(--red); }
.ff-k { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:12px; letter-spacing:.06em; color:var(--gold); font-weight:500; }
.fixfirst.green .ff-k { color:var(--green); } .fixfirst.red .ff-k { color:var(--red); }
.fixfirst strong { color:var(--ink); }
@media (max-width:640px){ .fixfirst{grid-template-columns:1fr;gap:6px} }

footer { padding:32px 0 0; font-size:12.5px; color:var(--slate); display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; }
code { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:.85em; }
"""


def build(cfg):
    sym = CUR.get(cfg["currency"], "$")
    camp = load("campaign")
    adset = load("adset")
    ads = load("ad")

    all_rows = camp or adset or ads
    result_col, result_label = pick_result_column(camp + adset + ads)

    # ---------- no data at all
    if not all_rows:
        return page_shell(
            kicker=f"{date.today():%a %d %b %Y}".upper() + " · META ADS — DAILY BRIEF",
            headline="Connected and running. Meta has not reported any delivery yet.",
            dateline="This page rebuilds itself every morning at 06:00. "
                     "The moment your ads serve, it fills in on its own.",
            body="""
<section>
  <div class="na">
    <strong>Nothing is broken.</strong> The pull ran, reached your ad account and came
    back with zero rows. That means Meta has no delivery to report yet — not that
    the connection failed.
    <ul>
      <li>A campaign that went live today usually shows nothing for several hours.</li>
      <li>Meta lags reporting by 15–30 minutes even once it starts.</li>
      <li>An ad still in review has not served at all yet.</li>
      <li>A paused campaign, or one with a spend limit already hit, reports nothing.</li>
    </ul>
    <p style="margin:14px 0 0">Worth a check in Ads Manager: is the campaign
    <strong>Active</strong> rather than <em>In review</em> or <em>Off</em>, and does the
    account have a valid payment method? Those are the two things that keep a
    correctly built campaign from ever serving.</p>
  </div>

  <div class="flag-box">
    <strong>Nothing for you to run.</strong> This page is rebuilt by GitHub every morning
    at 06:00 Lagos time. To force it sooner: your repo → <strong>Actions</strong> →
    <strong>Meta Ads — daily brief</strong> → <strong>Run workflow</strong>.
  </div>
</section>""")

    # ---------- date spine
    days = sorted({r["date_start"] for r in all_rows if r.get("date_start")})
    if not days:
        days = [date.today().isoformat()]
    d_last = days[-1]
    d_first = days[0]

    by_day = defaultdict(list)
    for r in all_rows:
        by_day[r.get("date_start")].append(r)

    daily_spend = [agg(by_day[d])["spend"] for d in days]
    daily_clicks = [agg(by_day[d])["link_clicks"] for d in days]
    daily_res = [sum(num(r, result_col) for r in by_day[d]) if result_col else 0 for d in days]
    short_labels = [d[5:] for d in days]

    # ---------- windows
    def window(n, offset=0):
        sel = days[max(0, len(days) - n - offset): len(days) - offset]
        rows = [r for d in sel for r in by_day[d]]
        return add_results(agg(rows), rows, result_col), sel

    total = add_results(agg(all_rows), all_rows, result_col)
    yday_t, _ = window(1)
    wk, wk_days = window(7)
    prev, prev_days = window(7, 7)

    spend_day = div(total["spend"], len(days))

    # ---------- headline
    if total["spend"] == 0:
        headline = "Ads are live but nothing has spent yet. There is no performance to read."
    elif total["results"] > 0:
        headline = (f"{fmt_money(total['spend'], sym)} across {len(days)} days bought "
                    f"{fmt_int(total['results'])} {result_label.lower()} at "
                    f"{fmt_money(total['cpr'], sym)} each.")
    elif total["link_clicks"] > 0:
        headline = (f"{fmt_money(total['spend'], sym)} across {len(days)} days bought "
                    f"{fmt_int(total['link_clicks'])} link clicks at "
                    f"{fmt_money(total['cpc'], sym)} each, and no results have landed yet.")
    else:
        headline = (f"{fmt_money(total['spend'], sym)} spent across {len(days)} days "
                    f"with zero link clicks. The creative or the targeting is the problem.")

    # ---------- read this first
    verdict_cls, verdict_k, verdict_txt = account_verdict(total, wk, prev, cfg, sym, result_label, len(days))

    # ---------- ledger
    ledger = f"""
  <div class="ledger">
    <div class="cell"><div class="label">Spend / day</div>
      <div class="value">{fmt_money(spend_day, sym)}</div>
      <div class="sub">{fmt_money(total['spend'], sym)} over {len(days)} day{'s' if len(days) != 1 else ''}</div></div>
    <div class="cell"><div class="label">Cost per link click</div>
      <div class="value">{fmt_money(total['cpc'], sym)}</div>
      <div class="sub {'good' if total['cpc'] and total['cpc'] <= cfg['target_cpc'] else 'bad' if total['cpc'] else ''}">target {fmt_money(cfg['target_cpc'], sym)} · {fmt_int(total['link_clicks'])} clicks</div></div>
    <div class="cell"><div class="label">Link CTR</div>
      <div class="value">{fmt_pct(total['link_ctr'])}</div>
      <div class="sub {'good' if total['link_ctr'] >= 1.0 else 'warn' if total['link_ctr'] >= 0.5 else 'bad'}">{fmt_int(total['impressions'])} impressions · {fmt_pct(total['ctr'])} all-click CTR</div></div>
    <div class="cell"><div class="label">{esc(result_label)}</div>
      <div class="value">{fmt_int(total['results'])}</div>
      <div class="sub {'good' if total['results'] and total['cpr'] <= cfg['target_cpr'] else 'bad' if total['results'] else 'warn'}">{(fmt_money(total['cpr'], sym) + ' each · target ' + fmt_money(cfg['target_cpr'], sym)) if total['results'] else 'nothing attributed yet'}</div></div>
  </div>"""

    # ---------- section 1: week vs week
    s1 = section_week(wk, prev, wk_days, prev_days, yday_t, d_last, sym, result_label)

    # ---------- section 2: trend
    s2 = f"""
<section id="s2">
  <div class="section-head"><h2><span class="snum">2</span>The daily trend</h2>
    <span class="note">{esc(d_first)} → {esc(d_last)}</span></div>
  <p class="section-intro">Every bar is one day. The dashed line is the period average. Hover a bar for the exact figure.</p>
  <div class="two">
    <div>
      <div class="chart-title">Spend per day ({esc(cfg['currency'])})</div>
      {columns(daily_spend, short_labels, unit="")}
      <div class="axis-note">Peak {fmt_money(max(daily_spend) if daily_spend else 0, sym)} · average {fmt_money(spend_day, sym)}</div>
    </div>
    <div>
      <div class="chart-title">Link clicks per day</div>
      {columns(daily_clicks, short_labels)}
      <div class="axis-note">Peak {fmt_int(max(daily_clicks) if daily_clicks else 0)} · average {div(sum(daily_clicks), len(days)):.1f}</div>
    </div>
  </div>
  {"" if not any(daily_res) else f'''
  <h3>{esc(result_label)} per day</h3>
  {columns(daily_res, short_labels)}
  <div class="axis-note">Total {fmt_int(sum(daily_res))} over {len(days)} days</div>'''}
</section>"""

    # ---------- entity tables
    s3 = entity_section(3, "Campaigns", camp, "campaign_name", cfg, sym, result_col, result_label)
    s4 = entity_section(4, "Ad sets", adset, "adset_name", cfg, sym, result_col, result_label)
    s5 = entity_section(5, "Ads — which creative is working", ads, "ad_name", cfg, sym, result_col, result_label)

    # ---------- actions
    s6 = actions_section(camp, adset, ads, cfg, sym, result_col, result_label, total, len(days))

    body = f"""
  <div class="fixfirst {verdict_cls}">
    <span class="ff-k">{esc(verdict_k)}</span>
    <span>{verdict_txt}</span>
  </div>
{s1}{s2}{s3}{s4}{s5}{s6}
  <footer>
    <span>Built from your own Meta Marketing API pull · no Supermetrics · {esc(cfg['currency'])}</span>
    <span>Generated {datetime.now():%Y-%m-%d %H:%M}</span>
  </footer>"""

    acct = (all_rows[0].get("account_name") or "META ADS").upper()
    return page_shell(
        kicker=f"{date.today():%a %d %b %Y}".upper() + f" · {esc(acct)} — DAILY BRIEF",
        headline=headline,
        dateline=f"Window <strong>{esc(d_first)} → {esc(d_last)}</strong> · "
                 f"{len(days)} days · all figures in {esc(cfg['currency'])} · "
                 f"results measured as <strong>{esc(result_label.lower())}</strong>",
        body=body,
        ledger=ledger,
        toc=True)


def account_verdict(total, wk, prev, cfg, sym, result_label, ndays):
    """The 'read this first' box."""
    if total["spend"] == 0:
        return ("", "READ THIS FIRST",
                "<strong>Nothing has spent yet.</strong> The account is connected and the pull works, "
                "but there is no delivery to judge. Leave it alone until it has spent for at least "
                "three full days — a campaign's first 24 hours are the learning phase and tell you nothing.")

    if ndays < 3:
        return ("", "READ THIS FIRST",
                f"<strong>Only {ndays} day{'s' if ndays != 1 else ''} of data.</strong> Meta's learning phase runs "
                "roughly 3–7 days or 50 results, whichever comes first. Numbers this early swing wildly. "
                "Read this page as a delivery check, not a verdict — do not turn anything off yet.")

    if total["results"] > 0 and total["cpr"] <= cfg["target_cpr"]:
        return ("green", "READ THIS FIRST",
                f"<strong>The account is inside target.</strong> {fmt_money(total['cpr'], sym)} per result "
                f"against a {fmt_money(cfg['target_cpr'], sym)} target, on {fmt_int(total['results'])} "
                f"{result_label.lower()}. The right move on a winner is to leave it running and raise budget "
                "slowly — no more than 20% every three days, or you reset the learning phase.")

    if total["link_clicks"] == 0:
        return ("red", "FIX THIS FIRST",
                f"<strong>{fmt_money(total['spend'], sym)} spent and not one link click.</strong> "
                "That is a creative problem, not a bidding problem. People are seeing the ad and scrolling past. "
                "Change the image and the first line of the copy before you change anything else.")

    if total["results"] == 0:
        return ("red", "FIX THIS FIRST",
                f"<strong>{fmt_int(total['link_clicks'])} link clicks and zero results.</strong> "
                "Clicks are landing but nothing follows. Either the destination is not converting, or the "
                "result you are optimising for is not being tracked. Check the link opens correctly on a phone "
                "before you touch the budget.")

    ratio = total["cpr"] / cfg["target_cpr"] if cfg["target_cpr"] else 0
    return ("red" if ratio > 1.5 else "", "READ THIS FIRST",
            f"<strong>{fmt_money(total['cpr'], sym)} per result against a {fmt_money(cfg['target_cpr'], sym)} "
            f"target — {ratio:.1f}× over.</strong> Section 5 shows which ads are carrying the cost. "
            "Turn off the worst performer before you touch anything else; spreading budget thinner across "
            "everything makes every ad worse.")


def section_week(wk, prev, wk_days, prev_days, yday, d_last, sym, result_label):
    if len(prev_days) < 3:
        return f"""
<section id="s1">
  <div class="section-head"><h2><span class="snum">1</span>This week</h2>
    <span class="note">{esc(wk_days[0] if wk_days else '')} → {esc(wk_days[-1] if wk_days else '')}</span></div>
  <p class="section-intro">There is not yet a full previous week to compare against, so this is the raw week only.</p>
  <div class="table-scroll"><table>
    <thead><tr><th>Last {len(wk_days)} days</th><th class="num">Total</th></tr></thead>
    <tbody>
      <tr><td><strong>Spend</strong></td><td class="num">{fmt_money(wk['spend'], sym)}</td></tr>
      <tr><td>Impressions</td><td class="num">{fmt_int(wk['impressions'])}</td></tr>
      <tr><td>Reach</td><td class="num">{fmt_int(wk['reach'])}</td></tr>
      <tr><td>Frequency</td><td class="num">{wk['freq']:.2f}</td></tr>
      <tr><td><strong>Link clicks</strong></td><td class="num">{fmt_int(wk['link_clicks'])}</td></tr>
      <tr><td>Link CTR</td><td class="num">{fmt_pct(wk['link_ctr'])}</td></tr>
      <tr><td>Cost per link click</td><td class="num">{fmt_money(wk['cpc'], sym)}</td></tr>
      <tr><td>CPM</td><td class="num">{fmt_money(wk['cpm'], sym)}</td></tr>
      <tr><td><strong>{esc(result_label)}</strong></td><td class="num">{fmt_int(wk['results'])}</td></tr>
      <tr><td>Cost per result</td><td class="num">{fmt_money(wk['cpr'], sym) if wk['results'] else '—'}</td></tr>
    </tbody></table></div>
  <div class="flag-box">
    <strong>Yesterday ({esc(d_last)}) is still attributing.</strong> It took
    {fmt_money(yday['spend'], sym)} and shows {fmt_int(yday['results'])} {esc(result_label.lower())}.
    Meta fills conversions in over 24–72 hours, so a zero on the newest day is normal.
    It only becomes a signal if it is still zero in tomorrow's brief.
  </div>
</section>"""

    rows = [
        ("Spend", fmt_money(prev["spend"], sym), fmt_money(wk["spend"], sym), dx(delta(wk["spend"], prev["spend"])), False),
        ("Impressions", fmt_int(prev["impressions"]), fmt_int(wk["impressions"]), dx(delta(wk["impressions"], prev["impressions"])), False),
        ("Reach", fmt_int(prev["reach"]), fmt_int(wk["reach"]), dx(delta(wk["reach"], prev["reach"])), False),
        ("Frequency", f"{prev['freq']:.2f}", f"{wk['freq']:.2f}", dx(delta(wk["freq"], prev["freq"]), good_when_down=True), False),
        ("Link clicks", fmt_int(prev["link_clicks"]), fmt_int(wk["link_clicks"]), dx(delta(wk["link_clicks"], prev["link_clicks"])), True),
        ("Link CTR", fmt_pct(prev["link_ctr"]), fmt_pct(wk["link_ctr"]), dx(delta(wk["link_ctr"], prev["link_ctr"])), False),
        ("Cost per link click", fmt_money(prev["cpc"], sym), fmt_money(wk["cpc"], sym), dx(delta(wk["cpc"], prev["cpc"]), good_when_down=True), False),
        ("CPM", fmt_money(prev["cpm"], sym), fmt_money(wk["cpm"], sym), dx(delta(wk["cpm"], prev["cpm"]), good_when_down=True), False),
        (result_label, fmt_int(prev["results"]), fmt_int(wk["results"]), dx(delta(wk["results"], prev["results"])), True),
        ("Cost per result",
         fmt_money(prev["cpr"], sym) if prev["results"] else "—",
         fmt_money(wk["cpr"], sym) if wk["results"] else "—",
         dx(delta(wk["cpr"], prev["cpr"]), good_when_down=True), True),
    ]
    trs = "".join(
        f'<tr><td>{"<strong>" + esc(a) + "</strong>" if bold else esc(a)}</td>'
        f'<td class="num">{b}</td><td class="num"><strong>{c}</strong></td><td class="num">{d}</td></tr>'
        for a, b, c, d, bold in rows)

    return f"""
<section id="s1">
  <div class="section-head"><h2><span class="snum">1</span>This week against the week before</h2>
    <span class="note">{esc(prev_days[0])}–{esc(prev_days[-1])} vs {esc(wk_days[0])}–{esc(wk_days[-1])}</span></div>
  <p class="section-intro">Two non-overlapping weeks. Green means the number moved the way you want — for costs
    that is down, for clicks and results that is up.</p>
  <div class="table-scroll"><table class="wide-table" style="min-width:600px">
    <thead><tr><th>Whole account</th><th class="num">Previous 7d</th><th class="num">Last 7d</th><th class="num">Change</th></tr></thead>
    <tbody>{trs}</tbody></table></div>
  <div class="flag-box">
    <strong>Yesterday ({esc(d_last)}) is still attributing.</strong> It took
    {fmt_money(yday['spend'], sym)} and shows {fmt_int(yday['results'])} {esc(result_label.lower())}.
    Meta fills conversions in over 24–72 hours, so a zero on the newest day is normal —
    it only counts as a signal if it is still zero tomorrow.
  </div>
</section>"""


INTROS = {
    3: ("Sorted by spend, highest first — the top row is costing you the most, whether or not it is working. "
        "The dot and the tag on the right are the verdict; the grey line under each name says why."),
    4: ("Inside each campaign, this is where the targeting actually lives. Two ad sets running the same ad to "
        "different people will not perform the same, and this is where that shows up."),
    5: ("This is the one that tells you what to make next. Same audience, same budget — the only thing that "
        "changed is the picture and the words, so a gap here is a creative gap."),
}


def entity_section(n, title, rows, name_key, cfg, sym, result_col, result_label):
    if not rows:
        return f"""
<section id="s{n}">
  <div class="section-head"><h2><span class="snum">{n}</span>{esc(title)}</h2></div>
  <div class="na">No {esc(title.lower())} data in this pull. Run
    <code>python meta_ads.py --level {"campaign" if n == 3 else "adset" if n == 4 else "ad"}</code>.</div>
</section>"""

    grouped = defaultdict(list)
    for r in rows:
        grouped[r.get(name_key) or "(unnamed)"].append(r)

    items = []
    for name, rs in grouped.items():
        t = add_results(agg(rs), rs, result_col)
        flag, tag, why = judge(t, cfg)
        items.append((name, t, flag, tag, why))

    items.sort(key=lambda x: -x[1]["spend"])
    maxspend = max((i[1]["spend"] for i in items), default=0)

    trs = []
    for name, t, flag, tag, why in items:
        trs.append(f"""<tr>
      <td><span class="row-flag {flag}"></span>{esc(name)}<span class="why">{esc(why)}</span></td>
      <td class="num">{fmt_money(t['spend'], sym)}</td>
      <td class="num">{fmt_int(t['impressions'])}</td>
      <td class="num">{fmt_int(t['link_clicks'])}</td>
      <td class="num">{fmt_pct(t['link_ctr'])}</td>
      <td class="num">{fmt_money(t['cpc'], sym) if t['link_clicks'] else '—'}</td>
      <td class="num">{fmt_int(t['results'])}</td>
      <td class="num">{fmt_money(t['cpr'], sym) if t['results'] else '—'}</td>
      <td class="num"><span class="tag {tag}">{tag}</span></td></tr>""")

    bars = "".join(
        hbar(name, t["spend"], maxspend, fmt_money(t["spend"], sym),
             cls={"green": "green", "gold": "gold", "red": "red", "slate": "soft"}[flag])
        for name, t, flag, _, _ in items[:8])

    winners = sum(1 for i in items if i[3] == "winner")
    wasters = sum(1 for i in items if i[3] == "waste")

    return f"""
<section id="s{n}">
  <div class="section-head"><h2><span class="snum">{n}</span>{esc(title)}</h2>
    <span class="note">{len(items)} live · {winners} inside target · {wasters} burning money</span></div>
  <p class="section-intro">{esc(INTROS.get(n, INTROS[3]))}</p>
  <div class="chart-title">Where the money went</div>
  {bars}
  <h3>The numbers</h3>
  <div class="table-scroll"><table class="wide-table">
    <thead><tr><th>Name</th><th class="num">Spend</th><th class="num">Impr.</th><th class="num">Link clicks</th>
      <th class="num">Link CTR</th><th class="num">CPC</th><th class="num">{esc(result_label)}</th>
      <th class="num">Cost/result</th><th class="num">Verdict</th></tr></thead>
    <tbody>{"".join(trs)}</tbody></table></div>
</section>"""


def actions_section(camp, adset, ads, cfg, sym, result_col, result_label, total, ndays):
    """Concrete next steps, ranked, generated from what the data actually shows."""
    sym_t = fmt_money(cfg["target_cpr"], sym)
    plans = []

    # worst and best ad
    def best_worst(rows, key):
        g = defaultdict(list)
        for r in rows:
            g[r.get(key) or "(unnamed)"].append(r)
        scored = []
        for nm, rs in g.items():
            t = add_results(agg(rs), rs, result_col)
            if t["spend"] <= 0:
                continue
            score = t["cpr"] if t["results"] else (t["cpc"] * 3 if t["link_clicks"] else 9e9)
            scored.append((score, nm, t))
        scored.sort()
        return (scored[0] if scored else None), (scored[-1] if scored else None)

    best, worst = best_worst(ads, "ad_name") if ads else (None, None)

    if ndays < 3:
        plans.append(("P3", "Wait. Do not touch anything.",
                      f"You have {ndays} day{'s' if ndays != 1 else ''} of data. Meta's learning phase needs "
                      "3–7 days or 50 results. Editing budget, audience or creative restarts that phase and "
                      "throws away what it has learned. Come back to this page on day 4."))

    if total["spend"] > 0 and total["link_clicks"] == 0:
        plans.append(("P0", "Replace the creative.",
                      f"{fmt_money(total['spend'], sym)} spent, zero link clicks. The ad is being shown and "
                      "ignored. Swap the image and rewrite the first line — that is the only line most people read."))

    if total["results"] == 0 and total["link_clicks"] > 0:
        plans.append(("P0", "Check the destination on a phone.",
                      f"{fmt_int(total['link_clicks'])} people clicked and nothing was recorded. Open the link on "
                      "your own phone. If it loads fine, the result you are optimising for is probably not "
                      "being tracked at all."))

    if worst and worst[2]["spend"] >= cfg["target_cpr"] * 3:
        _, wname, wt = worst
        plans.append(("P1", f"Turn off: {wname}",
                      f"{fmt_money(wt['spend'], sym)} spent for "
                      f"{fmt_int(wt['results']) + ' ' + result_label.lower() if wt['results'] else 'nothing'}"
                      f"{' at ' + fmt_money(wt['cpr'], sym) + ' each' if wt['results'] else ''}. "
                      f"Against a {sym_t} target this is the clearest loser in the account."))

    if best and best[2]["results"] > 0 and best[2]["cpr"] <= cfg["target_cpr"]:
        _, bname, bt = best
        plans.append(("P2", f"Raise budget on: {bname}",
                      f"{fmt_money(bt['cpr'], sym)} per result against a {sym_t} target. Raise its budget by "
                      "20% and leave it three days. Bigger jumps reset the learning phase and you lose the edge."))

    if total["impressions"] > 0 and agg(camp or adset or ads)["freq"] > 3:
        plans.append(("P1", "Audience is getting worn out.",
                      f"Frequency is {agg(camp or adset or ads)['freq']:.2f} — the same people are seeing this "
                      "ad over and over. Widen the audience or refresh the creative before CPM climbs further."))

    plans.append(("P3", "Tomorrow morning",
                  "Run <code>python meta_ads.py --days 30</code> then "
                  "<code>python build_dashboard.py</code>. Two commands, same page, one day newer."))

    cards = "".join(
        f'<div class="p"><div class="pbadge {p.lower()}">{p}</div>'
        f'<div><h4>{esc(t)}</h4><p>{b}</p></div></div>'
        for p, t, b in plans)

    return f"""
<section id="s6">
  <div class="section-head"><h2><span class="snum">6</span>What to do about it</h2>
    <span class="note">ranked, most urgent first</span></div>
  <p class="section-intro">Generated from the numbers above, not from general advice. P0 is on fire, P3 can wait.
    Do them in order and change one thing at a time — change three and you will never know which one worked.</p>
  <div class="plan">{cards}</div>
</section>"""


def page_shell(kicker, headline, dateline, body, ledger="", toc=False):
    nav = ""
    if toc:
        nav = ('<nav class="toc">'
               '<a href="#s1">1 Week on week</a><a href="#s2">2 Daily trend</a>'
               '<a href="#s3">3 Campaigns</a><a href="#s4">4 Ad sets</a>'
               '<a href="#s5">5 Ads</a><a href="#s6">6 What to do</a></nav>')
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>The Morning Brief — Meta Ads</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="wrap">
  <header class="masthead">
    <div class="kicker">{kicker}</div>
    <h1>{headline}</h1>
    <div class="dateline">{dateline}</div>
    {nav}
  </header>
{ledger}
{body}
</div></body></html>"""


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Build the Meta Ads morning brief.")
    p.add_argument("--target-cpc", type=float, default=DEFAULTS["target_cpc"],
                   help="what you want to pay per link click")
    p.add_argument("--target-cpr", type=float, default=DEFAULTS["target_cpr"],
                   help="what you want to pay per result")
    p.add_argument("--min-clicks", type=int, default=DEFAULTS["min_clicks"],
                   help="below this many clicks a row is marked 'too thin to judge'")
    p.add_argument("--currency", default=DEFAULTS["currency"], help="USD, EUR, GBP, AUD, CAD, NGN")
    p.add_argument("--out", default=str(OUT), help="output html path")
    p.add_argument("--open", action="store_true", dest="do_open", help="open it after building")
    a = p.parse_args()

    cfg = {
        "target_cpc": a.target_cpc,
        "target_cpr": a.target_cpr,
        "min_clicks": a.min_clicks,
        "min_impr": DEFAULTS["min_impr"],
        "currency": a.currency.upper(),
    }

    html_out = build(cfg)
    outp = Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(html_out, encoding="utf-8")
    print(f"Wrote {outp}  ({len(html_out):,} bytes)")

    if a.do_open:
        webbrowser.open(outp.resolve().as_uri())


if __name__ == "__main__":
    main()

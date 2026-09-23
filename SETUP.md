# Setup — runs on GitHub, nothing on your PC

Once this is done, GitHub pulls your Meta Ads data every morning at 06:00 Lagos
time, rebuilds the dashboard, and saves everything back into the repo. You never
run a command again.

---

## Step 1 — Make the repo

1. Go to **github.com/new**
2. Name: `meta-ads-brief`
3. Choose **Public**
4. Tick **Add a README file**
5. Click **Create repository**

> **What public means here.** Your code, your CSVs and your dashboard are
> readable by anyone who finds the URL — spend, campaign names, CPCs, the lot.
> Your secrets are *not*: GitHub encrypts those and never shows them, in the
> repo or in a log.
>
> The real rule that comes with a public repo: **workflow logs are public too.**
> Never print a token, an App Secret or a password in a workflow. That is why
> token refresh is done in your browser instead — see `REFRESH-TOKEN.md`.
>
> If you would rather keep the numbers private, make the repo Private instead.
> Everything below still works; only GitHub Pages (Step 6A) needs a paid plan.

## Step 2 — Upload the files

On the repo page: **Add file** → **Upload files**.

Drag in all of these, keeping the folder structure:

```
meta_ads.py
build_dashboard.py
requirements.txt
SETUP.md
README.md
REFRESH-TOKEN.md
.gitignore
.github/workflows/daily.yml
.github/workflows/refresh-token.yml
```

GitHub's web uploader flattens folders. If `.github/workflows/` does not survive
the drag, create those two files by hand instead:
**Add file** → **Create new file** → type `.github/workflows/daily.yml` as the
name (the slashes make the folders) → paste the contents → **Commit**.
Repeat for `refresh-token.yml`.

Click **Commit changes**.

## Step 3 — Add your secrets

**Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add these four, one at a time:

| Name | Value |
|---|---|
| `META_APP_ID` | `1840312887337592` |
| `META_APP_SECRET` | from Meta app → Settings → Basic → App Secret → Show |
| `META_ACCESS_TOKEN` | your 60-day token |
| `META_AD_ACCOUNT_ID` | `act_969263457291386` |

Secrets are encrypted. Nobody can read them back out, including you — you can
only replace them. That is why they are safe here and not in the code.

### Optional — your targets

Same page, **Variables** tab → **New repository variable**:

| Name | Example | What it does |
|---|---|---|
| `TARGET_CPC` | `0.30` | what you want to pay per link click |
| `TARGET_CPR` | `1.50` | what you want to pay per result |
| `CURRENCY` | `USD` | `USD`, `EUR`, `GBP`, `AUD`, `CAD`, `NGN` |

Leave them out and it uses $0.35, $2.00, USD.

## Step 4 — Give the workflow permission to commit

**Settings** → **Actions** → **General** → scroll to **Workflow permissions** →
select **Read and write permissions** → **Save**.

Without this the job runs but cannot save the results.

## Step 5 — Run it once by hand

**Actions** tab → **Meta Ads — daily brief** → **Run workflow** → **Run workflow**.

Watch it go green. It takes about a minute.

If it goes red, click the failed step and read the last line. The usual causes:
- `Token invalid or expired` — the token in the secret is the short-lived one, not the 60-day one
- `Missing in .env` — a secret name is misspelled
- `Permission denied` on the commit step — Step 4 was skipped

## Step 6 — See the dashboard

Three ways, easiest first.

**A. GitHub Pages** — do this one

**Settings** → **Pages** → under **Source** choose **GitHub Actions** → done.

The next run publishes it to:

```
https://<your-username>.github.io/meta-ads-brief/
```

Bookmark that on your phone. It updates itself every morning. Send me that link
and I can read your live numbers whenever you want my take on them.

**B. Download it**

**Actions** → click the latest run → scroll to **Artifacts** → download
`dashboard-N` → unzip → open `index.html`.

**C. Open it from the repo**

The file lives at `public/index.html` in the repo. GitHub shows it as code, not
as a page. Click **Download raw file**, then open it.

---

## Daily rhythm

Nothing. It runs itself at 06:00.

To force a run: **Actions** → **Meta Ads — daily brief** → **Run workflow**.

## Every ~60 days

The daily job opens an issue titled *"Meta access token expires in N days"*.
When it does, follow **REFRESH-TOKEN.md** — two minutes, done in your browser.

Never paste a token into a workflow, an issue or a commit on a public repo.

## What it costs

Nothing. GitHub Actions is free for 2,000 minutes a month on private repos.
This job uses about 1 minute a day — roughly 30 minutes a month.

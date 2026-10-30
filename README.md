# Indian Trader Skills for Claude

Two Claude Code skills for the Indian stock market (NSE), written with
Claude. Standard-library Python 3, nothing to `pip install`.

| Skill | What it does |
| --- | --- |
| [`trader-news-india`](skills/trader-news-india/SKILL.md) | NSE corporate filings, Indian news headlines (Google News India) and the % move vs previous close, for your stocks or a whole index. Shows only what is new, in IST, tags each item, flags market-moving filings with `!`, and scores **sentiment** (▲ positive / ▼ negative / · neutral, with the reason) plus a per-stock sentiment table. A **relevance filter** keeps only headlines that name the company and drops market roundups. |
| [`trader-scanner-india`](skills/trader-scanner-india/SKILL.md) | Chart scanner: daily setups (20-day breakout/breakdown, bull flag, reclaim/lost 20-day average, oversold, oversold bounce, overbought) and intraday opening-range breakouts up and down from 9:15 IST. Data from **Zerodha Kite Connect** (after the daily login) or free Yahoo data. Writes `trader/watchlist.json`, which the news skill reads. |

Both are education and tooling, not financial advice. Neither places,
sizes or suggests orders.

## Install (new Mac, or after a reset)

```bash
git clone https://github.com/dikshaRai/indian-trader-skills.git
cd indian-trader-skills
./install.sh
```

`install.sh` copies both folders to `~/.claude/skills/`. Restart Claude
Code; the skills then appear as `/trader-news-india` and
`/trader-scanner-india`.

For reading filing PDFs: `brew install poppler`.

## Daily routine

| Time (IST) | Do |
| --- | --- |
| Before 9:15 | `python3 ~/.claude/skills/trader-scanner-india/kite_login.py` (Zerodha token, expires daily) |
| ~8:30 | `/trader-news-india --index NIFTY50` (pre-market brief) |
| Before 9:15 | `/trader-scanner-india daily --index NIFTY100` (yesterday's setups) |
| After 9:35 | `/trader-scanner-india orb --index NIFTY50`, then `/trader-news-india` on the hits |
| During market | `/loop 15m /trader-scanner-india orb --index NIFTY50` |
| After 22:00 | `/trader-news-india --index NIFTY50` (NSE's filing feed resets at midnight) |

## Automation (runs on its own, Mon-Fri)

`automation/trader_day.py` runs the skills on a schedule, merges each
scanner hit with its news (holding break + agreeing news first), writes a
Markdown report and shows a Mac notification. It does not need Claude open
and never logs in or places orders.

| Time (IST) | Job | Report |
| --- | --- | --- |
| 08:35 | reminder: notifies only if today's Zerodha login is missing | |
| 08:45 | premarket: Nifty 50 news sentiment + Nifty 100 daily setups | `HHMM-premarket.md` |
| 09:40, 10:10, 10:40, 11:10, 12:10, 13:10, 14:10 | orb: Nifty 50 opening-range hits + news on each | `HHMM-orb.md` |
| 22:15 | evening: the day's Nifty 100 filings before NSE's feed resets | `HHMM-evening.md` |

Reports land in `<data folder>/trader/reports/YYYY-MM-DD/`, and
`trader/reports/latest.md` is always the newest.

Install the schedule yourself (it adds launchd jobs to your Mac), pointing
it at the folder that holds `trader/`:

```bash
./automation/schedule.sh install "/path/to/your/trading folder"
./automation/schedule.sh status
./automation/schedule.sh remove        # stop everything
```

Run any job by hand: `python3 automation/trader_day.py orb --data "/path/to/folder"`.
The only manual step left is the morning `kite_login.py`. The Mac must be
awake for jobs to run (a missed job runs when it wakes), and its time zone
must be IST.

## Common commands

```bash
# News
/trader-news-india RELIANCE TCS HDFCBANK
/trader-news-india --index NIFTY50                 # or NIFTYNEXT50, NIFTY100
/trader-news-india --index NIFTY100 --no-headlines --no-moves   # filings only, seconds
/trader-news-india --index NIFTY50 --sentiment negative        # only negative headlines
/trader-news-india RELIANCE --loose --roundups                  # turn the relevance filter off

# Scanner
/trader-scanner-india daily --index NIFTY500
/trader-scanner-india daily --symbols RELIANCE,TCS,M&M
/trader-scanner-india orb --index NIFTY50 --at 10:30
/trader-scanner-india orb --index NIFTY50 --day 2026-10-29     # replay a past session
```

Indices: NIFTY50, NIFTYNEXT50, NIFTY100, NIFTY500, MIDCAP150, SMALLCAP250
(scanner); NIFTY50, NIFTYNEXT50, NIFTY100 (news). Lists come from NSE's
published constituent files and refresh every 7 days.

## Zerodha Kite Connect setup (one time)

1. In [developers.kite.trade](https://developers.kite.trade), note your app's
   redirect URL (any URL works, e.g. `http://127.0.0.1`).
2. `python3 ~/.claude/skills/trader-scanner-india/kite_login.py --init`:
   type the API key and secret (the secret prompt is hidden). Saved to
   `~/.config/trader-india/kite.json`, readable only by you.
3. Each trading morning: `python3 ~/.claude/skills/trader-scanner-india/kite_login.py`,
   log in on Zerodha's page, paste the redirect address **into the terminal**.

Rules that keep the account safe:

- Never paste the API secret, request token or access token into a chat.
  If one gets pasted, regenerate the secret in the Kite console.
- The config file lives outside this repo and is never committed.
- `kite_data.py` only reads the instrument list and historical candles. It
  cannot place orders.

Without a token for the day the scanner falls back to Yahoo and says so.

## Data sources

| Source | Used for | Notes |
| --- | --- | --- |
| NSE `nsearchives.nseindia.com` | symbol list, index constituents, filings RSS, filing PDFs | public files only; the RSS holds the current day |
| Google News RSS (India) | headlines | search by company name; generic names can pull unrelated stories |
| Zerodha Kite Connect | scanner candles | official, needs subscription + daily login |
| Yahoo Finance | scanner fallback, news price line | free, unofficial, can lag and drop 5-minute bars |

NSE's internal website APIs and BSE's API block scripts and are
deliberately not used.

## Known limits

- No NSE holiday calendar: on a holiday the tools say there is no data.
- BSE-only stocks are not covered.
- F&O ban list, ASM/GSM surveillance and circuit limits are not checked.
- On trending days most large caps break their opening range; the ORB
  signal is weak on its own.

## Background

Built on 29-30 Oct 2026 after reviewing
[jakeschincariol/day-trader-skill](https://github.com/jakeschincariol/day-trader-skill)
(US-only). These are independent India versions written from the same
setup rules, not copies of that code.

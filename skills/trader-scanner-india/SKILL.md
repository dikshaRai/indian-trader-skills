---
name: trader-scanner-india
description: >-
  Chart Scanner for Indian stocks (NSE). Scans Nifty 50, Nifty Next 50,
  Nifty 100, Nifty 500, Midcap 150 or Smallcap 250 (from NSE's published
  lists) or your own symbols for setups: 20-day breakouts and breakdowns,
  bull flags, reclaiming or losing the 20-day average, oversold, oversold
  bounce, overbought, and intraday opening-range breakouts up or down on
  5-minute bars from 9:15 IST. Free Yahoo data, filters by price and rupee
  turnover, writes trader/watchlist.json for trader-news-india. Use when the
  user says "scan Nifty", "find setups in NSE", "what is breaking out in
  India", "opening range breakout Nifty 50", "oversold Nifty 500 stocks",
  "build my Indian watchlist", "pre-market scan India", or before
  /trader-news-india.
argument-hint: "[daily | orb] [--index NIFTY50 ...] [--at HH:MM]"
---

# trader-scanner-india

The first step of an Indian day trade: read hundreds of free NSE charts and
list the ones that match a rule. A scan is a list of charts that match a
rule, not a list of stocks to buy, and a setup on a chart is not a
prediction. Most people who day trade lose money; the scanner does not
change that.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" daily                        # Nifty 500, ~25 s
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" daily --index NIFTY100       # ~5 s
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" daily --symbols RELIANCE,TCS,M&M
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" orb --index NIFTY50          # after 9:35 IST
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" orb --index NIFTY100 --at 10:30 --or-minutes 15
python3 "${CLAUDE_SKILL_DIR}/scan_india.py" orb --index NIFTY50 --day 2026-10-29   # replay a past session (last 5 days)
```

Map the user's words to `--index`: "Nifty" / "Nifty 50" -> NIFTY50,
"Nifty Next 50" / "Nifty Junior" -> NIFTYNEXT50, "Nifty 100" -> NIFTY100,
"Nifty 500" / "the whole market" -> NIFTY500, "midcaps" -> MIDCAP150,
"smallcaps" -> SMALLCAP250. Several can be combined. Bank Nifty, sector
indices and F&O lists are not built in: pass their symbols with `--symbols`.

Flags: `--min-price` (Rs 20), `--min-turnover-cr` (daily, Rs 5 crore of
today's turnover), `--or-minutes` (15), `--at HH:MM`, `--day YYYY-MM-DD`,
`--max-missing` (default 10 % of bars so far; range bars must be complete), `--max-confirm` (150),
`--show N`, `--json`, `--no-write`, `--now` (IST). Exit 0 = hits, 1 = none
or could not run, 2 = bad input.

## Setups

**daily** (daily closes only; today's bar counts only after 15:30 IST, so
a run before the close scans through yesterday):

| setup | rule |
| --- | --- |
| breakout_20d | last close above every close of the 20 sessions before it |
| breakdown_20d | last close below every close of the 20 before it |
| bull_flag | up > 10 % over the 10 sessions before the last 5, then 5 closes within 5 % |
| reclaim_ma20 | closed below the 20-day average, then above it |
| lost_ma20 | closed above the 20-day average, then below it |
| oversold | RSI 14 under 30 |
| oversold_bounce | RSI 14 under 30 yesterday and closed up today |
| overbought | RSI 14 over 70 |

**orb** (5-minute bars): the opening range is 9:15 to 9:15 + `--or-minutes`.
`orb_up` = the first completed bar to close above the range high,
`orb_down` = the first to close below the range low, with the trigger time.
Hits are listed by trigger time, then turnover.

## What it reads and writes

| file / feed | what |
| --- | --- |
| NSE `nsearchives.nseindia.com/content/indices/ind_*list.csv` | index constituents, cached 7 days |
| Yahoo spark / chart, `<SYMBOL>.NS` | daily closes, 5-minute bars (unofficial, can lag) |
| `trader/watchlist.json` | `hits[]` with plain NSE symbols, read by trader-news-india |
| `trader/state/scanner_india.json` | the index cache |

## Data source: Zerodha Kite Connect or Yahoo

`--source auto` (default) uses **Zerodha Kite Connect** when today's access
token is in `~/.config/trader-india/kite.json`, otherwise Yahoo, and says
which in the first line of the output. `--source kite` fails with a plain
message instead of falling back. Kite gives official NSE candles with no
missing bars; it fetches one chart per stock at 3 a second (Nifty 50 ~20 s,
Nifty 500 ~3 min, daily or orb).

The user logs in, never Claude. Each trading morning the user runs, in
their own terminal:

```bash
python3 "${CLAUDE_SKILL_DIR}/kite_login.py"          # --init the first time, --check to test
```

Rules for Claude, without exception:
- Never ask for, read, print or paste the API key, API secret, request
  token or access token, and never open `~/.config/trader-india/kite.json`.
  If the user pastes one into the chat, tell them to regenerate it in the
  Kite developer console.
- Never run `kite_login.py` yourself; tell the user to run it. You may run
  `kite_login.py --check`, which prints only yes or no.
- `kite_data.py` is read-only (instruments and historical candles). Never
  add order placement to it.
- If the output says "Kite token is not from today" or "rejected the
  token", tell the user to run `kite_login.py`, then rerun the scan.

## Steps

1. Pick the mode: before 9:15 or after 15:30 -> `daily`; between 9:35 and
   15:30 -> `orb` (or `daily` for yesterday's setups).
2. Run it. Tell the user how long a Nifty 500 run takes before starting
   (Yahoo ~25 s daily, ~3-5 min orb; Kite ~3 min either), and name the
   data source the output reports.
3. Report the counts line (requested, fetched, failed, filtered, hits)
   and the top hits per setup, most traded first. Say plainly when a large
   share of a big index triggers (common on trending days: the signal is
   then weak on its own).
4. Offer `/trader-news-india` on the hits: it reads `trader/watchlist.json`
   by default. A setup into results day, a record date, an F&O ban or
   ASM/GSM surveillance is a different trade.

During the session: `/loop 15m /trader-scanner-india orb --index NIFTY50`.

## Limits

- No NSE holiday table: on a holiday the scan says there is no bar for the
  day. Check NSE's holiday list when in doubt.
- Yahoo is free and unofficial: prices can lag, bars go missing, and a
  symbol can fail. Kite data is official but needs the daily login. Either
  way the scan lists failures and never fills gaps.
- Rules use closes (daily) and completed 5-minute bars only: no volume
  surge, no news, no circuit limits.

## Safety

Education and tooling, not financial advice. This skill only reads charts
and writes a watchlist. It never places, sizes or suggests orders.

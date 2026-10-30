---
name: trader-day-india
description: >-
  Trading-day agent for Indian stocks (NSE). Runs the whole routine in one
  step: pre-market brief (Nifty 50 news sentiment + Nifty 100 daily
  setups), opening-range scan of the Nifty 50 with news checked on every
  hit (holding break + agreeing news first), or the evening filings sweep.
  Reviews the results like an analyst (fixes wrong sentiment labels, opens
  important NSE filing PDFs, flags results days, whipsaws and record
  dates), writes a short brief and saves a dated report. Use when the user
  says "run my trading day", "morning brief", "pre-market", "check the
  market now", "what's setting up", "ORB plus news", "evening filings", or
  when a scheduled task calls /trader-day-india.
argument-hint: "[premarket | orb | evening] [--index NIFTY50]"
---

# trader-day-india

One command for the routine that otherwise takes four: login check, scan,
news on the hits, review. It reads charts and news only. It never logs in
to Zerodha, never places, sizes or suggests orders, and never says what a
stock will do next.

The engine is `trader_day.py` in this folder; it calls the installed
`trader-scanner-india` and `trader-news-india` skills.

```bash
python3 -I "${CLAUDE_SKILL_DIR}/trader_day.py" premarket --data "$DATA" --force
python3 -I "${CLAUDE_SKILL_DIR}/trader_day.py" orb --data "$DATA" --force          # --index NIFTY100
python3 -I "${CLAUDE_SKILL_DIR}/trader_day.py" evening --data "$DATA" --force
python3 -I "${CLAUDE_SKILL_DIR}/../trader-scanner-india/kite_login.py" --check   # prints yes/no only
```

`$DATA` is the folder that holds `trader/` (watchlist, state, reports):
`/Users/diksharaikwar/Diksha Directory/1. STOCK MARKET/6. Pine Editor scripts`
unless the user names another. Each run prints the report path and writes
`trader/reports/latest.md`. Drop `--force` to make weekend runs exit
silently (what a schedule wants).

## Pick the mode

No argument: choose by the IST clock.

| IST | mode |
| --- | --- |
| before 9:15 | premarket |
| 9:35 to 15:30 | orb |
| 15:30 to 9:15 next day | evening (after 22:00 is best: NSE's filing feed resets at midnight) |
| 9:15 to 9:35 | say the opening range is still forming; offer premarket now or orb after 9:35 |

Weekends: say the market is closed; offer evening or a past-session replay
(`/trader-scanner-india orb --day YYYY-MM-DD`).

## Steps

1. Run `kite_login.py --check`. If it says no, tell the user to run
   `python3 ~/.claude/skills/trader-scanner-india/kite_login.py` in their
   own terminal, and continue (the scans fall back to Yahoo and say so).
   Never run the login, never read `~/.config/trader-india/kite.json`, and
   if the user pastes a token or secret, tell them to regenerate it.
2. Run the mode. It takes about 1-2 minutes (orb and premarket) or seconds
   (evening). Read the report it wrote.
3. Review before writing anything:
   - **Sentiment labels** are rule-based. Read each headline you cite; fix
     obvious misreads ("record profits amid cost pressures" is positive)
     and say you corrected it.
   - **`!` filings** for stocks in the top rows: open the PDF
     (`curl -s -A "Mozilla/5.0" -o f.pdf URL && pdftotext -layout f.pdf -`)
     and report what it actually says. XBRL (.xml) filings: name them and
     say the details are on NSE.
   - **Risk flags**: results today or tonight, record dates (T+1: hold by
     the close the day before), whipsaws (both sides triggered), very wide
     ranges, and the "most of the index triggered" warning.
4. Write the brief, short:
   - orb: the counts line; a table of up to 8 rows, holding + agrees first,
     then conflicts; one line on whipsaws and faded breaks; risk flags.
   - premarket: most positive and most negative stocks with the reason;
     results due today; the daily setups worth a look.
   - evening: every `!` filing in plain words (results numbers, dividend
     and record date, deal, rating), read from the PDFs.
   End with the report path and: "Charts and news, not a list of stocks to
   buy. Place orders yourself in Kite."
5. Scheduled runs (no user in the chat): do steps 1-4 and finish. Do not
   ask questions; put anything that needs the user in the brief.

## Limits

- Reads public NSE files, Google News and Zerodha Kite candles (or Yahoo).
  F&O ban, ASM/GSM and circuit limits are not checked: say so when a stock
  is a candidate.
- No NSE holiday table: on a holiday the scan reports no data; say the
  market looks closed.
- Most day traders lose money. Never turn the brief into advice.

---
name: trader-bos-india
description: >-
  BOS / CHoCH market-structure scanner for Indian stocks (NSE): finds stocks
  where a Break of Structure or Change of Character has happened and where
  a BUY BOS (or SELL) signal fired, with entry, stop (breakout candle low /
  high) and target, and whether SL or TP has been hit since. A Python port
  of the user's Pine script "Gold Navigator + Regime (BOS/CHoCH)". Scans
  Nifty 50 + Nifty Next 50 by default on 15-minute candles (5, 30, 60
  minute or daily on request), Zerodha Kite data or Yahoo. Use when the
  user says "BOS scan", "which stocks gave BOS", "buy BOS signal", "CHoCH",
  "market structure break", "structure scan Nifty", "BOS on the breakout candle", "regime breakout", "range breakout", or /trader-bos-india.
argument-hint: "[--index NIFTY50 NIFTYNEXT50] [--tf 15] [--recent 25]"
---

# trader-bos-india

Runs the BOS / CHoCH rules from the user's Pine script over a whole index
and lists what fired. A signal is a chart that matched a rule, not a trade
to take. Never place, size or suggest orders.

```bash
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py"                              # Nifty 50 + Next 50, 15 min
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --index NIFTY50 --tf 5
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --symbols RELIANCE,ITC --tf 60
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --tf D --swing 5              # daily structure
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --no-sell --recent 10         # BUY only, last 10 candles
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --early                       # BOS on the breakout candle, last 2 candles
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --regime-only --recent 4      # range breakouts out of regime zones
python3 -I "${CLAUDE_SKILL_DIR}/bos_india.py" --regime-tf 240               # 4 h regime filtering 15 min BOS
```

**Early mode** (`--early`, = `--confirm 0 --recent 2`): flags the BOS as
soon as the breakout candle closes, without waiting for the 2
follow-through candles; entry = breakout close. Use when the user says
"BOS immediately", "on the breakout candle", "just broke". It catches the
move sooner but includes breaks that fail on the next candle: say so in
the brief. Good with `/loop 15m /trader-bos-india --early`.

Run it from the folder that holds `trader/` (the user's
`6. Pine Editor scripts` folder). It needs the `trader-scanner-india`
skill installed next to it (index lists, Kite and Yahoo data). Kite is used
when today's token exists; otherwise Yahoo. Nifty 100 on Kite takes about
40 seconds.

Map the user's words: "Nifty" -> `--index NIFTY50`, "Next 50" ->
`NIFTYNEXT50`, both / no index named -> the default (both). "5 min chart"
-> `--tf 5`, "hourly" -> `--tf 60`, "daily" -> `--tf D` (use `--swing 5`
on daily: 12 daily bars each side finds very few pivots).

## Rules (Pine defaults)

| step | rule | flag |
| --- | --- | --- |
| swings | pivot high/low with 12 bars each side | `--swing` |
| break | bull candle closes above the last unbroken swing high (or the protected high after a bearish structure) by 0.1 ATR | `--confirm-by`, `--min-break`, `--no-protected` |
| filters | body >= 0.8 ATR14, ADX14 >= 25, 10 bars since the last mark | `--min-body`, `--adx-min` (0 = off), `--cooldown` |
| confirm | the next 2 candles must not close back below the level | `--confirm` |
| label | CHoCH if against the current structure, else BOS | |
| BUY | entry = confirming close, SL = breakout candle low, TP = entry + 2 x risk | `--tp-r`, `--tp-pct`, `--sl-buffer`, `--max-risk-pct` |
| one at a time | no new signal until SL or TP | `--many` |

SELL is the mirror image (`--no-sell` hides it). The Pine target is in
dollars for gold; for stocks it is 2 R by default (or `--tp-pct`).

## Regime zones and range breakouts

`regime.py` ports the Pine script's Regime Engine (`f_regime`, same
defaults) and runs it on the scan candles (15 min by default, the Pine
default regime timeframe). It finds **SIDEWAYS / CHOPPY / CONSOLIDATION**
zones (12-bar range under 3.5 base ATR, 3+ midline crosses, low drift, not
trending by ER / R2) and reports:

- **Range Breakout / Range Breakdown**: a candle closed out of the zone by
  0.1 base ATR (or a strong trend carried it past the edge). Shown with the
  zone, its type and start, the break close and the distance from the edge
  now. Reported on the break candle itself (the Pine label appears one
  candle later). Tags `range_breakout` / `range_breakdown`.
- **Regime now** per stock (zone type or TRENDING UP / DOWN) and a count.
- **Filter**: as in Pine, BUY/SELL signals are blocked while a zone was
  active on the previous candle. `--no-regime-block` allows them.
- **`--regime-tf`** picks the regime timeframe, like the Pine "Regime
  timeframe" input: `5 15 30 60 120 240 D` (default = `--tf`). 2 h and 4 h
  are built from hourly candles starting 9:15. Each scan candle uses the
  last regime candle that closed before it opened (no repaint), so a 4 h
  zone filters 15-minute signals the way your chart does. Map "1 hour
  regime" -> `60`, "4 hour" -> `240`, "daily" -> `D`. A higher regime
  timeframe fetches a second set of candles (Nifty 100 on Kite: ~+40 s).
- `--regime-only`: only zones and range breakouts. With `--symbols` the
  current zones are listed too.

Use for "regime breakout", "range breakout", "which stocks broke out of
consolidation / sideways", "regime scan".

## Sector strength, macro tilt and pre-results warnings

Every run (except `--regime-only`) also shows:

- **Sector strength today**: average move vs the previous close of each
  sector's stocks (`sectors.py` maps the Nifty 100), strongest 5 and
  weakest 3. BUY signals are sorted strongest sector first, SELL weakest
  first, so stocks riding the day's theme come to the top.
- **Macro tilt** (needs `trader-geo-india` next to this skill;
  `--no-macro` skips it, ~10 s): flagged moves in Brent, gold, USD/INR,
  dollar index, US 10y, Nasdaq, Hang Seng, mapped to sectors
  (`+Brent crude down 9.5%` = tailwind for oil marketers, paints,
  aviation; `-Gold up 1.5%` = headwind for jewellers).
- **Warnings on open signals** (`⚠`):
  - `RESULTS DUE <date>` / `RESULTS OUT <date>`: results headline in
    the last 7 days pointing at yesterday to 3 days ahead (`events.py`,
    Google News, cached 12 h in `trader/state/results_calendar.json`;
    `--no-events` skips it, ~1 s per signal stock the first time).
  - `RUN-UP +x% in 5 sessions` (or `SELL-OFF`): at or above
    `--runup-pct` (5).
  - `PRICED-IN RISK`: a BUY with results due and a run-up: good news may
    already be in the price, and the stock can fall on good results
    (APOLLOHOSP 5-Nov: +10% in the week before, profit +32%, opened up,
    then -3.8% in the first 15 minutes, stop hit).

In the brief, lead with the sector ranking and global moves, then the BUY
signals in the strongest sectors. Call out every `PRICED-IN RISK` and
`RESULTS DUE` signal: a stop does not protect against a results gap.
The results lookup reads headlines and can miss or misdate a results day;
say so when it matters, and check NSE's board-meeting notice.

Only completed candles are used, so marks do not repaint. Small
differences from TradingView are possible (pivot ties, ADX warm-up, data
vendor); if a mark disagrees with the chart, the chart wins.

## Output

- **BUY / SELL signals, last N candles**: entry, SL, TP, risk %, price
  now, and status (`open`, `TP hit <time>`, `SL hit <time>`).
- **Older signals still open**: fired before the window, SL/TP not hit yet.
- **Bullish / Bearish BOS / CHoCH**: the level broken, break and confirm
  times, price now (a mark without a signal = a signal was still open).
- **Structure now**: how many stocks are in bullish vs bearish structure.
- Writes `trader/watchlist.json` (tags `bos_up`, `choch_up`, `buy_signal`
  ...), so `/trader-news-india` checks news on the hits next.

## Brief

1. Counts line and data source.
2. New BUY signals, open ones first, most traded first: entry, SL, TP,
   risk %. Flag a risk under 0.3 % (stop too tight: a wick takes it out)
   and over 3 % (wide stop).
3. Signals already resolved today (TP hit / SL hit).
4. Bullish and bearish marks without a signal, briefly.
5. Range breakouts / breakdowns, most traded first.
   (Put the sector ranking, global moves and `⚠` warnings first, see above.)
6. Risks: F&O ban / ASM not checked, results
   or record dates (offer `/trader-news-india` on the hits).
7. End: "Charts that matched the rule, not a list of stocks to buy. Place
   orders yourself in Kite."

---
name: trader-news-india
description: >-
  News Monitor for Indian stocks (NSE). Tracks exchange filings and news on
  every stock you watch: NSE corporate announcements (results, board
  meetings, dividends, bonus, buyback, order wins, resignations, credit
  ratings, pledges) and Indian news headlines via Google News India, plus
  how far each stock is from yesterday's close. Shows only what is new since
  the last check, in IST, tags each item and flags market-moving filings.
  Use when the user says "any news on RELIANCE", "why is TCS moving", "news
  on my watchlist", "NSE announcements", "morning briefing", "pre-market
  news", "check filings", or names NSE symbols and asks about news.
argument-hint: "[NSE symbols]"
---

# trader-news-india

Before a setup becomes a trade, read what the company told the exchange and
what the press is saying. This skill does both for every NSE symbol you
watch, and shows only what is new.

Tool in this folder (standard library Python, no keys, no logins):

```bash
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --tickers RELIANCE TCS HDFCBANK
python3 "${CLAUDE_SKILL_DIR}/news_india.py"                    # trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --tickers INFY --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --no-headlines     # NSE filings only
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --json
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --index NIFTY50 --no-headlines      # filings, all 50
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --index NIFTY50 NIFTYNEXT50          # all 100, ~3-4 min
python3 "${CLAUDE_SKILL_DIR}/news_india.py" --index NIFTYNEXT50 --tickers IRCTC  # index + extras
```

Symbols are plain NSE symbols (`RELIANCE`; `RELIANCE.NS` is accepted too).

**Index lists.** `--index NIFTY50`, `NIFTYNEXT50`, or `NIFTY100` (both) adds
every constituent, read from NSE's published constituent CSVs and cached 7
days, so rebalancing is picked up automatically. Map the user's words:
"Nifty 50" / "Nifty" -> NIFTY50, "Nifty Next 50" / "Nifty Junior" ->
NIFTYNEXT50, "Nifty 100" / "both" -> NIFTY100.

For a whole index, start with `--no-headlines` and tell the user it takes
about 1 minute for 50 stocks or 2 minutes for 100 (one price request a
second); add `--no-moves` too for filings only in a few seconds. Then run
headlines only for the stocks with a `!` filing or MOVING. Headlines for all
100 add about 2 more minutes. With more than 20 stocks the price block lists
only the MOVING ones, biggest first. Other indices (Bank Nifty etc.) are not
supported; pass their symbols with `--tickers`.

## Sources

| feed | what |
| --- | --- |
| NSE `EQUITY_L.csv` | symbol to company name, cached 7 days |
| NSE Online announcements RSS | every corporate filing of roughly the last 24 hours, one request for all tickers |
| Google News RSS (India edition) | headlines per company from Indian and global outlets |
| Yahoo Finance chart `<SYMBOL>.NS` | last price against previous close (unofficial, may lag or rate-limit) |
| `trader/state/news_india.json` | what has been shown (30 days) and the symbol cache |

Only public feeds are used. NSE's internal website APIs and BSE's API block
scripts and are deliberately not touched.

## The rules

- **Filings beat headlines.** An NSE filing is what the company told the
  exchange. If a headline disagrees, the filing wins. Open the PDF link.
- **Headlines are leads, not facts.** Read the story before reporting it.
  Never summarise a paywalled story you could not read: say so.
- **`!` marks a filing that usually moves a stock:** financial results,
  board meeting outcome or intimation, acquisition or merger, resignation or
  new MD/CEO/CFO, credit rating, pledge, bonus, split, buyback, rights issue,
  fund raising, order win, insolvency, penalty, clarification on price
  movement.
- **MOVING** marks a stock 3 % or more from the previous close (`--move-pct`).
  A big move with no news is worth saying out loud.
- **No predictions.** Report what was published and the move. Never say what
  the stock will do next.

## Sentiment

Every item gets a rule-based sentiment score: ▲ positive, ▼ negative,
· neutral, with the phrases that produced it on the next line
(`sentiment -3: -target price cuts, -miss estimates`). The output opens
with a per-stock table: net score and how many ▲ / ▼ / · items each stock
has, most positive first. `--sentiment negative` (or positive / neutral)
shows only those headlines; filings are always kept. `--json` carries
`sentiment`, `sentiment_score` and `sentiment_why` per item.

What it scores: results direction (profit/revenue up or down, "rise in net
profit", loss narrows or widens), beats or misses estimates, upgrades and
downgrades, target raised or cut/trimmed, buy/sell calls, order wins,
regulatory approvals (USFDA, VAI), record or 52-week highs and lows,
share-price moves ("shares jump 6%", "falls 3%"), buybacks and bonus,
resignations, probes, penalties, fraud, defaults, warning letters, ASM/GSM.
Cost increases ("fuel bill jumps") are not counted as positive, and a
"despite ..." clause is ignored.

How Claude uses it:
- It is a first pass for sorting, not a verdict. Read the headline: the
  rules miss sarcasm, questions ("buy or sell?"), and stories about another
  company that mention this one. Correct an obviously wrong label in the
  brief and say so.
- Lead the brief with the per-stock table, then the strongest ▼ items (they
  are the risks to a long setup) and ▲ items.
- Opinion pieces, single unknown sources and "stocks to watch" lists stay
  neutral in weight even if the score says otherwise.
- Never turn sentiment into advice: "news is mostly negative" is a report;
  "so sell it" is not allowed.

## Steps

1. Run the check. Exit code 1 means nothing new; `--all` shows seen items,
   `--dry-run` leaves the state alone.
2. Read every `!` filing first (open the PDF), then anything tagged
   results, regulatory, risk, capital or corporate-action, then MOVING tickers.
3. Write a short brief per ticker: what happened, source and link, the move,
   and one line on why it matters to the trade (for example "results are
   tomorrow after market hours: the stock can gap at 9:15").
4. Note India-specific risks when they appear: F&O ban list, ASM/GSM
   surveillance, upper or lower circuit, record dates for dividends or bonus.

During market hours (9:15 to 15:30 IST): `/loop 15m /trader-news-india`.

## Limits

- The NSE RSS holds only the current calendar day: it resets at midnight
  IST. Filings made after the close (results, dividends, board outcomes
  usually land 15:30-23:00) vanish from it overnight. Run a check late in
  the evening (after 22:00) to catch them; a morning run before 9:15 sees
  only filings since midnight. Say so in a pre-market brief, and fill the
  gap with headlines (Google News carries the overnight results stories).
  For history, check the company page on nseindia.com.
- BSE-only stocks are not covered.
- Google News search is by company name, so very generic names can pull in
  unrelated stories. Drop those from the brief.

## Safety

Education and tooling, not financial advice. This skill only reads and
reports, and never places or suggests orders.

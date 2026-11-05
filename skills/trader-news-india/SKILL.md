---
name: trader-news-india
description: >-
  News Monitor for Indian stocks (NSE). Tracks exchange filings and news on
  every stock you watch: NSE corporate announcements (results, board
  meetings, dividends, bonus, buyback, order wins, resignations, credit
  ratings, pledges) and Indian news headlines via Google News India, plus
  how far each stock is from yesterday's close. Shows only what is new since
  the last check, in IST, tags each item and flags market-moving filings.
  Also FII / DII flows and F&O positioning (fii_dii.py). Use when the user says "FII DII data", "foreign investors buying", "any news on RELIANCE", "why is TCS moving", "news
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

## FII / DII flows (`fii_dii.py`)

Who is buying India: foreign (FII/FPI) and domestic (DII: mutual funds,
insurers) money, and how FIIs are positioned in index futures.

```bash
python3 -I "${CLAUDE_SKILL_DIR}/fii_dii.py"            # cash flows, NSDL FPI, F&O positioning, ~5 s
python3 -I "${CLAUDE_SKILL_DIR}/fii_dii.py" --days 10  # 10 sessions of positioning
```

Use when the user says "FII", "DII", "FPI", "foreign investors",
"institutional buying / selling", "FII data", or asks who is driving
the market.

| part | source | when |
| --- | --- | --- |
| cash buy / sell / net, FII and DII (₹ crore) | NSE provisional (`nseindia.com/api/fiidiiTradeReact`) | after ~18:00 IST; only the latest day, so each run stores it in `trader/state/fii_dii.json` and the 5- and 20-day sums build up from there |
| FPI confirmed equity and debt net | NSDL daily trends | a day after the trade |
| FII / DII / Pro / Client index futures long vs short, index call and put net | NSE participant-wise open interest (nsearchives) | after ~19:00 IST, history by date |
| **FPI money by sector**: net buying / selling per sector for the last two fortnights, assets held | NSDL fortnightly sector report (latest one found automatically) | twice a month (15th and month-end, published a few days later) |
| **Stocks**: bulk and block deals of the day, parties matched to FII (foreign funds and banks) or DII (mutual funds, insurers) by name; net per stock | NSE `bulk.csv`, `block.csv` | after the close |

Deals by same-day proprietary / high-frequency traders (Graviton, HRTI,
Plutus Wealth...) are tagged `prop` and hidden: they buy and sell the same
shares the same day. `--all-deals` shows every deal, `--no-sectors`,
`--no-deals` skip parts. Name matching can miss an institution trading
through an unfamiliar entity: say so when it matters.

There is no daily stock-by-stock FII / DII split in India: bulk and block
deals (only large trades) and the quarterly shareholding patterns are the
public stock-level data. Sector flows are fortnightly.

In the brief:
1. Cash: FII net and DII net, who absorbed whom (FII selling met by DII
   buying is the usual Indian pattern); the multi-day sums once history exists.
2. F&O: FII index futures long % and the change from the previous session
   (below 30 % = heavily short, above 70 % = heavily long; a jump in longs
   or short covering after a heavy-short stretch is worth saying);
   clients (retail) usually hold the opposite side.
3. Sectors: the top FPI buying and selling sectors for the month and
   whether the latest fortnight turned (e.g. IT bought in the second half
   after selling); stocks with FII or DII bulk / block deals.
4. Link to the day: sector moves and BOS signals in the sectors FIIs are
   buying (banks, NBFCs on FII buying days), and global cues from
   `/trader-geo-india`.

This reports positions and flows, never a forecast. The NSE endpoint is an
internal API that may start blocking scripts: if it fails, say so and use
NSDL plus the participant OI file.

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

## Relevance filter

Google News matches a company name anywhere in an article, so by default
a headline is kept only if its **title names the company**: its NSE name,
a known alias (RIL, HUL, SBI, L&T, IndiGo, Airtel, Zomato...) or the
symbol. Look-alike companies are excluded (ITC Hotels is not ITC, M&M
Financial is not M&M, SBI Life is not SBI, HDFC Life is not HDFC Bank).
Market roundups ("stocks to watch", "top laggards", Sensex/Nifty wraps,
"10 stocks to post earnings") are dropped too. The output's last `note:`
line says how many were dropped. `--roundups` keeps roundups, `--loose`
turns the filter off. Filings are never filtered.

If a real story about a company is missing because headlines use another
name, add the name to `ALIASES` in `news_india.py`; a wrong look-alike goes
in `NOT_THIS`.

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
   **Results filings**: do not stop at "profit up X %". From the results
   PDF compare (a) revenue growth with profit growth, (b) other income
   now vs a year ago (a jump in other income can make profit look better
   than the business: APOLLOHOSP Q2 FY27 standalone other income 2.4x,
   profit before tax +24 % but about +12 % without it), (c) one-offs and
   exceptional items, (d) the margin. Say whether numbers beat or missed
   estimates only if a named source says so, and note how far the stock
   ran up before the results (`/trader-bos-india` shows the 5-session move).
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

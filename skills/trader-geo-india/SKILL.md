---
name: trader-geo-india
description: >-
  Geopolitical and global-macro watch for the Indian stock market (NSE):
  crude oil / Middle East, India-Pakistan, India-China, US tariffs and
  H-1B visas, Russia sanctions, the Fed and the dollar, Red Sea shipping
  and China's economy, plus market gauges (Brent, gold, USD/INR, dollar
  index, US 10-year yield, India VIX, Nifty and sector indices, US and
  Asian indices). Flags big moves and lists the Indian sectors and stocks
  usually exposed. Use when the user says "geopolitical news", "global
  cues", "war news impact on market", "crude impact on India", "tariff
  news", "what's happening globally", "macro check", or /trader-geo-india.
argument-hint: "[--theme crude] [--hours 24] [--links]"
---

# trader-geo-india

Reads world news and global market gauges and maps them to the Indian
sectors that usually feel them. It reports sensitivities, never forecasts,
and never places, sizes or suggests orders.

```bash
python3 -I "${CLAUDE_SKILL_DIR}/geo_india.py"                          # all themes, 24 h, gauges (~45 s)
python3 -I "${CLAUDE_SKILL_DIR}/geo_india.py" --theme crude --theme shipping --links
python3 -I "${CLAUDE_SKILL_DIR}/geo_india.py" --no-headlines           # gauges only, ~10 s
python3 -I "${CLAUDE_SKILL_DIR}/geo_india.py" --hours 72 --max 10
```

Themes (`--theme`, repeatable): `crude`, `india-pakistan`, `india-china`,
`us-trade`, `russia`, `fed-dollar`, `shipping`, `china-economy`. Map the
user's words: "war / Iran / Israel / oil" -> crude, "border / Pakistan /
terror" -> india-pakistan, "tariff / Trump / visa / H-1B" -> us-trade,
"Fed / dollar / FII" -> fed-dollar, "Red Sea / Houthi / freight" -> shipping.

## What it shows

- **Gauges**: move vs previous close and over 5 sessions. `<== BIG MOVE`
  when Brent >= 2 %, gold >= 1.5 %, USD/INR >= 0.3 %, dollar index >= 0.5 %,
  US 10y >= 8 bps, India VIX >= 6 %, Nifty >= 1 %, sector indices 1.5-2 %,
  overseas indices 1-2 %. Each flag lists the Indian sectors usually exposed
  (oil up: OMCs, paints, INDIGO, tyres, the rupee hurt; ONGC, OIL helped;
  a down-move reverses it).
- **Themes**: Google News (India edition) headlines per theme with
  `+` escalation (attack, sanctions, tariff hike, hawkish) / `-` easing
  (ceasefire, deal, tariff cut, rate cut) by word rule, and the exposed
  sectors and stocks.

## Brief

1. One line on the overall tone: which gauges flagged and which themes are
   busiest with escalation headlines.
2. Gauges that flagged, with the exposed Indian sectors (say which way:
   oil DOWN helps OMCs, paints, aviation).
3. Per busy theme: the 2-3 headlines that matter, read and summarised (not
   just the `+`/`-` label; the rule misreads "oil plunges" style headlines,
   and opinion / social posts carry little weight). Name the exposed NSE
   stocks.
4. Link to what the user is watching: open BOS signals, results days,
   holdings in exposed sectors. Offer `/trader-news-india` on those stocks.
5. End: "Sensitivities, not forecasts. Place orders yourself in Kite."

## Limits

- Yahoo gauges are unofficial and can lag; India VIX and sector indices
  update only during NSE hours. Before 9:15 the Indian rows show
  yesterday's close; overseas rows show their latest session.
- Headlines are leads, not facts; Google News search can pull in
  unrelated stories. Drop them from the brief. Paywalled stories: say so.
- The sector map is a fixed list of usual sensitivities, not a model.
  Read the actual move (e.g. GIFT Nifty, the opening candle) before
  assuming the usual reaction.

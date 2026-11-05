#!/usr/bin/env python3
"""Geopolitical and global-macro watch for the Indian market. Standard library only.

    python3 geo_india.py                       # all themes, last 24 h, plus market gauges
    python3 geo_india.py --theme crude --theme us-trade --hours 48
    python3 geo_india.py --no-gauges           # headlines only
    python3 geo_india.py --json

Two parts:
  gauges   Brent, gold, USD/INR, dollar index, US 10-year yield, India VIX,
           Nifty, Bank Nifty, sector indices and the main overseas indices
           (Yahoo chart, unofficial): move vs previous close and over 5 days.
           A big move raises a flag with the Indian sectors usually exposed.
  themes   Google News (India edition) searches per theme: crude / Middle
           East, India-Pakistan, India-China, US tariffs and trade, Russia
           sanctions, Fed and the dollar, shipping lanes, China economy.
           Each headline is marked escalation (+) or easing (-) by rule.

The sector lists are the usual sensitivities (who pays for crude, who
exports to the US...), not a forecast. Nothing here says what a stock will
do next. Exit 0 = something to report, 1 = nothing, 2 = bad input.
"""

import argparse
import datetime as _dt
import email.utils
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; trader-geo-india/1.0)"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
CHART = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=10d&interval=1d"
PAUSE = 0.6

# name, Yahoo symbol, flag threshold (% move vs previous close; yields in bps)
GAUGES = [
    ("Brent crude", "BZ=F", 2.0),
    ("Gold", "GC=F", 1.5),
    ("USD/INR", "INR=X", 0.3),
    ("Dollar index", "DX-Y.NYB", 0.5),
    ("US 10y yield", "^TNX", 8.0),
    ("India VIX", "^INDIAVIX", 6.0),
    ("Nifty 50", "^NSEI", 1.0),
    ("Bank Nifty", "^NSEBANK", 1.2),
    ("Nifty IT", "^CNXIT", 1.5),
    ("Nifty Metal", "^CNXMETAL", 2.0),
    ("Nifty Pharma", "^CNXPHARMA", 1.5),
    ("Nifty Energy", "^CNXENERGY", 1.5),
    ("S&P 500", "^GSPC", 1.0),
    ("Nasdaq", "^IXIC", 1.5),
    ("Nikkei", "^N225", 1.5),
    ("Hang Seng", "^HSI", 2.0),
]

# What a big gauge move usually touches in India (up-move wording; a down-move reverses it)
GAUGE_IMPACT = {
    "Brent crude": "oil up hurts importers: OMCs (BPCL, HPCL, IOC), paints (ASIANPAINT, BERGEPAINT), "
                   "aviation (INDIGO), tyres (MRF, APOLLOTYRE), the rupee; helps ONGC, OIL, RELIANCE upstream",
    "Gold": "gold up helps gold lenders (MUTHOOTFIN, MANAPPURAM); squeezes jewellers' margins (TITAN, KALYANKJIL); a fear gauge",
    "USD/INR": "weaker rupee helps exporters: IT (TCS, INFY, HCLTECH), pharma (SUNPHARMA, DRREDDY); hurts importers and foreign-debt holders",
    "Dollar index": "strong dollar usually pulls foreign money (FII) out of India and weighs on the rupee and metals",
    "US 10y yield": "higher US yields usually mean FII selling in India; weighs on banks, NBFCs and rate-sensitive stocks",
    "India VIX": "VIX up = traders pay more for protection; wider intraday swings, stops get hit more easily",
    "Nifty IT": "follows the Nasdaq, the rupee and US tariff / visa news",
    "Nifty Metal": "follows China demand, LME prices and the dollar",
    "Nifty Pharma": "follows US FDA news, US tariff talk and the rupee",
    "Nifty Energy": "follows crude and government fuel-pricing moves",
    "S&P 500": "US mood sets the tone for India's open (via GIFT Nifty)",
    "Nasdaq": "US tech mood: Indian IT usually moves the same way",
    "Hang Seng": "China sentiment: metals and Asian risk appetite",
}

THEMES = {
    "crude": {
        "title": "Crude oil / Middle East",
        "queries": ["crude oil OPEC price", "Iran Israel attack oil", "Strait of Hormuz", "Saudi Arabia oil output"],
        "match": r"\b(crude|oil|brent|opec|iran|israel|hormuz|saudi|gaza|houthi|lebanon|hezbollah)\b",
        "impact": "OMCs (BPCL, HPCL, IOC), ONGC, OIL, RELIANCE, paints (ASIANPAINT), INDIGO, tyres, the rupee",
    },
    "india-pakistan": {
        "title": "India-Pakistan / security",
        "queries": ["India Pakistan border tension", "India Pakistan LoC army", "terror attack India Kashmir"],
        "match": r"\b(pakistan|loc|kashmir|terror|ceasefire|army|militant|infiltration)\b",
        "impact": "defence (HAL, BEL, BDL, MAZDOCK) usually bid; broad market and VIX react to escalation",
    },
    "india-china": {
        "title": "India-China",
        "queries": ["India China border LAC", "India China trade rare earth", "China export curbs India"],
        "match": r"\b(china|chinese|beijing|lac|galwan|rare earth|xi)\b",
        "impact": "electronics and auto supply chains (rare earths, APIs for pharma), metals, defence",
    },
    "us-trade": {
        "title": "US tariffs / trade deal / visas",
        "queries": ["US tariff India", "India US trade deal", "H-1B visa", "Trump tariff"],
        "match": r"\b(tariffs?|trade deal|trade talks?|h-1b|visa|duty|duties|trump|ustr)\b",
        "impact": "IT (TCS, INFY, HCLTECH, WIPRO), pharma exporters, textiles, auto parts, seafood, gems & jewellery",
    },
    "russia": {
        "title": "Russia-Ukraine / sanctions",
        "queries": ["Russia Ukraine war", "Russia sanctions oil India", "Russian oil India imports"],
        "match": r"\b(russia|russian|ukraine|kremlin|putin|sanction)\w*",
        "impact": "refiners buying Russian crude (RELIANCE, IOC, BPCL), fertiliser, metals, defence imports",
    },
    "fed-dollar": {
        "title": "Fed / dollar / global rates",
        "queries": ["Federal Reserve rate decision", "US inflation CPI", "dollar index yields", "FII outflow India"],
        "match": r"\b(fed|federal reserve|powell|rate cut|rate hike|inflation|cpi|yields?|dollar|fii|fpi)\b",
        "impact": "FII flows into India, banks and NBFCs, the rupee, rate-sensitive sectors (realty, autos)",
    },
    "shipping": {
        "title": "Shipping lanes / Red Sea / freight",
        "queries": ["Red Sea shipping attack", "Suez canal shipping", "container freight rates"],
        "match": r"\b(red sea|suez|shipping|freight|houthi|vessel|container|tanker)\b",
        "impact": "exporters' costs, shipping and ports (ADANIPORTS, SCI, CONCOR), oil import bill",
    },
    "china-economy": {
        "title": "China economy / stimulus",
        "queries": ["China stimulus economy", "China steel demand", "China PMI factory"],
        "match": r"\b(china|chinese|beijing|yuan|pmi|stimulus|property)\b",
        "impact": "metals (TATASTEEL, JSWSTEEL, HINDALCO, VEDL, NMDC), chemicals; China weakness can mean cheap imports into India",
    },
}

ESCALATE = re.compile(
    r"\b(attacks?|strikes?|struck|war|missiles?|drones? attack|bomb\w*|kill(?:s|ed)|clash\w*|escalat\w*|"
    r"sanctions? (?:on|against)|new sanctions|tariffs? (?:hike|raised?|on)|imposes?|slaps?|blockade|seiz\w+|"
    r"threat\w*|tension\w*|retaliat\w*|curbs?|ban(?:s|ned)?|surge[sd]?|spikes?|soar\w*|hawkish|outflows?)\b", re.I)
EASE = re.compile(
    r"\b(ceasefire|truce|peace|deal (?:signed|reached|agreed)|trade deal|agreement|talks? (?:progress|resume)|"
    r"de-?escalat\w*|eases?|easing|lifts?|cuts? tariffs?|tariff cut|waive\w*|exempt\w*|calm\w*|"
    r"rate cut|dovish|inflows?|plunge[sd]?|slump\w*|tumble[sd]?)\b", re.I)
# price words mean opposite things for crude (up = bad for India) and for flows; keep them neutral there
PRICE_WORDS = re.compile(r"\b(surge[sd]?|spikes?|soar\w*|plunge[sd]?|slump\w*|tumble[sd]?)\b", re.I)

ROUNDUP = re.compile(r"\b(stocks? to (?:watch|buy)|top gainers|top losers|sensex|nifty (?:today|live)|market live|"
                     r"live updates|horoscope|share price today|price prediction)\b", re.I)


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ist(t):
    return t.astimezone(IST).strftime("%d-%b %H:%M")


def gauge(sym):
    data = json.loads(http_get(CHART % urllib.parse.quote(sym)))
    res = data["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = res["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
    if price is None or len(closes) < 2:
        return None
    # last close may be today's (still moving) bar; previous close is the one before it
    last_t = _dt.datetime.fromtimestamp(res["timestamp"][-1], IST).date()
    mkt_t = _dt.datetime.fromtimestamp(res["meta"].get("regularMarketTime", res["timestamp"][-1]), IST).date()
    prev = closes[-2] if last_t == mkt_t else closes[-1]
    base5 = closes[-6] if len(closes) >= 6 else closes[0]
    return {"price": price, "prev": prev, "base5": base5, "as_of": mkt_t.isoformat()}


def collect_gauges(errors):
    out = []
    for name, sym, thr in GAUGES:
        try:
            g = gauge(sym)
        except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the run
            errors.append("%s: %s" % (name, str(e)[:80]))
            g = None
        time.sleep(PAUSE)
        if not g:
            continue
        bps = sym == "^TNX"
        # yields: change in basis points (Yahoo quotes ^TNX in percent); everything else: % change
        chg = (g["price"] - g["prev"]) * 100 if bps else (g["price"] / g["prev"] - 1) * 100
        chg5 = (g["price"] - g["base5"]) * 100 if bps else (g["price"] / g["base5"] - 1) * 100
        out.append({"name": name, "symbol": sym, "price": g["price"], "change": chg, "change_5d": chg5,
                    "unit": "bps" if bps else "%", "flag": abs(chg) >= thr, "as_of": g["as_of"]})
    return out


def score(title, theme):
    t = title
    if theme in ("crude", "fed-dollar"):
        t = PRICE_WORDS.sub("", t)
    up, dn = len(ESCALATE.findall(t)), len(EASE.findall(t))
    return up - dn


def collect_theme(key, hours, errors, seen):
    th = THEMES[key]
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)
    match = re.compile(th["match"], re.I)
    items = []
    for q in th["queries"]:
        try:
            root = ET.fromstring(http_get(GNEWS % urllib.parse.quote(q + " when:%dd" % max(1, round(hours / 24)))))
        except Exception as e:  # noqa: BLE001
            errors.append("%s / %s: %s" % (key, q, str(e)[:80]))
            continue
        time.sleep(PAUSE)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            src = it.find("source")
            source = src.text.strip() if src is not None and src.text else ""
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            try:
                when = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
            except (TypeError, ValueError):
                continue
            norm = re.sub(r"\W+", " ", title.lower()).strip()
            if when < cutoff or norm in seen or not match.search(title) or ROUNDUP.search(title):
                continue
            seen.add(norm)
            items.append({"theme": key, "title": title, "source": source, "time": when,
                          "link": it.findtext("link") or "", "score": score(title, key)})
    items.sort(key=lambda x: x["time"], reverse=True)
    return items


def render(gauges, themes, args, errors, now):
    lines = ["Geopolitics & global macro for the Indian market, %s, headlines from the last %g h." % (
        now.strftime("%a %d-%b-%Y %H:%M IST"), args.hours)]
    if gauges:
        lines += ["", "Market gauges (vs previous close / 5 sessions; Yahoo, may lag):"]
        for g in gauges:
            lines.append("  %-13s %12s  %+6.2f%s  5d %+6.2f%s %s" % (
                g["name"], "{:,.2f}".format(g["price"]), g["change"], g["unit"], g["change_5d"], g["unit"],
                " <== BIG MOVE" if g["flag"] else ""))
        flagged = [g for g in gauges if g["flag"] and g["name"] in GAUGE_IMPACT]
        if flagged:
            lines += ["", "What the big moves usually touch in India:"]
            for g in flagged:
                down = g["change"] < 0
                lines.append("  %s %s %.2f%s: %s%s" % (g["name"], "down" if down else "up", abs(g["change"]), g["unit"],
                                                       GAUGE_IMPACT[g["name"]],
                                                       " [this is a DOWN move: the effect runs the other way]"
                                                       if down and " up " in " " + GAUGE_IMPACT[g["name"]] else ""))
    summary = []
    for key, items in themes.items():
        if not items:
            continue
        esc = sum(1 for i in items if i["score"] > 0)
        eas = sum(1 for i in items if i["score"] < 0)
        summary.append((key, len(items), esc, eas))
    if summary:
        lines += ["", "Themes (headlines; + escalation / - easing, rule-based):"]
        for key, n, esc, eas in sorted(summary, key=lambda s: -(s[2] + s[1] / 100)):
            lines.append("  %-34s %3d headlines  +%d / -%d" % (THEMES[key]["title"], n, esc, eas))
    for key, items in themes.items():
        if not items:
            continue
        lines += ["", "== %s  (exposed: %s)" % (THEMES[key]["title"], THEMES[key]["impact"])]
        for i in items[: args.max]:
            mark = "+" if i["score"] > 0 else "-" if i["score"] < 0 else "·"
            lines.append("  %s %s  %s (%s)" % (mark, ist(i["time"]), i["title"], i["source"]))
            if args.links:
                lines.append("      " + i["link"])
    if not summary and not args.no_headlines:
        lines += ["", "No theme headlines in the window."]
    for e in errors:
        lines.append("note: could not read " + e)
    lines.append("note: + / - is a word rule (attack, sanctions, tariff hike vs ceasefire, deal, rate cut): read the headline.")
    lines.append("Sensitivities, not forecasts: nothing here says what a stock will do next.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Geopolitical / global-macro watch for the Indian market")
    ap.add_argument("--theme", action="append", choices=list(THEMES), help="repeat to pick themes (default: all)")
    ap.add_argument("--hours", type=float, default=24, help="headline window (default 24)")
    ap.add_argument("--max", type=int, default=6, help="headlines shown per theme (default 6)")
    ap.add_argument("--no-gauges", action="store_true")
    ap.add_argument("--no-headlines", action="store_true")
    ap.add_argument("--links", action="store_true", help="print article links")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = _dt.datetime.now(IST)
    errors, seen = [], set()
    gauges = [] if a.no_gauges else collect_gauges(errors)
    themes = {}
    if not a.no_headlines:
        for key in a.theme or list(THEMES):
            themes[key] = collect_theme(key, a.hours, errors, seen)
    if a.json:
        print(json.dumps({"as_of": now.isoformat(), "gauges": gauges,
                          "themes": {k: [dict(i, time=i["time"].isoformat()) for i in v] for k, v in themes.items()},
                          "errors": errors}, indent=2))
    else:
        print(render(gauges, themes, a, errors, now))
    return 0 if gauges or any(themes.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

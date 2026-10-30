#!/usr/bin/env python3
"""News monitor for Indian stocks (NSE). Standard library only.

Watches NSE corporate announcements and Indian news headlines for the stocks
you watch and prints only what is new since the last check, newest first, in
IST, with how far each stock has moved today.

    python3 news_india.py --tickers RELIANCE TCS HDFCBANK
    python3 news_india.py                          # tickers from trader/watchlist.json
    python3 news_india.py --tickers INFY --all --hours 72
    python3 news_india.py --no-headlines           # exchange filings only
    python3 news_india.py --json
    python3 news_india.py --index NIFTY50 --no-headlines   # filings for all 50
    python3 news_india.py --index NIFTY50 NIFTYNEXT50 --tickers IRCTC

Tickers are NSE symbols (RELIANCE, not RELIANCE.NS). --index adds every
constituent of NIFTY50 and/or NIFTYNEXT50 (NIFTY100 = both), read from NSE's
published lists and cached 7 days:
    https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv
    https://nsearchives.nseindia.com/content/indices/ind_niftynext50list.csv

Sources (public feeds only, no keys, no logins):
  - NSE symbol list, symbol -> company name (cached 7 days):
    https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
  - NSE corporate announcements RSS, one request for all tickers (about the
    last 24 hours of filings: results, board meetings, dividends, orders...):
    https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml
  - Google News RSS, India edition, one request per ticker:
    https://news.google.com/rss/search?q="<company>"+when:2d&hl=en-IN&gl=IN&ceid=IN:en
  - The move: Yahoo Finance chart for <SYMBOL>.NS (unofficial, can lag or
    rate-limit; skipped with a note if it fails).

State: trader/state/news_india.json remembers what you have seen (30 days).
Offline: --offline DIR reads EQUITY_L.csv, Online_announcements.xml,
gnews-<SYMBOL>.xml and chart-<SYMBOL>.json from DIR.

Headlines are leads, not facts: open the filing or story before acting, and
treat nothing here as advice.
"""

import argparse
import csv
import datetime as _dt
import email.utils
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
CHART = "https://query2.finance.yahoo.com/v8/finance/chart/%s.NS?range=1d&interval=5m"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/%s.csv"
INDICES = {"NIFTY50": "ind_nifty50list", "NIFTYNEXT50": "ind_niftynext50list"}
INDEX_ALIASES = {"NIFTY": ["NIFTY50"], "NIFTY_50": ["NIFTY50"], "NEXT50": ["NIFTYNEXT50"],
                 "NIFTY_NEXT_50": ["NIFTYNEXT50"], "NIFTYJR": ["NIFTYNEXT50"],
                 "NIFTY100": ["NIFTY50", "NIFTYNEXT50"]}
UA = "Mozilla/5.0 (compatible; trader-news-india/1.0)"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
KEEP_DAYS = 30
SYMBOLS_MAX_AGE_DAYS = 7
MOVE_PCT = 3.0
PAUSE = 1.0  # seconds between requests

# NSE filing subjects that usually move a stock: shown with "!"
IMPORTANT_SUBJECTS = re.compile(
    r"financial result|outcome of board meeting|board meeting intimation|acquisition|"
    r"amalgamation|merger|restructuring|demerger|scheme of arrangement|resignation|cessation|appointment of .*(md|ceo|cfo|managing)|"
    r"credit rating|pledge|bonus|buy ?back|split|sub-division|rights issue|fund rais|qip|"
    r"preferential issue|award of order|bagging|receipt of order|insolvency|default|"
    r"fraud|search|raid|penalty|show cause|suspension|delisting|clarification",
    re.I)

KEYWORDS = [
    ("results", r"\bresults?\b|\bQ[1-4]\b|\bprofit\b|\brevenue\b|\bEBITDA\b|\bearnings\b|\bguidance\b|\bmargin"),
    ("analyst", r"\bupgrade|\bdowngrade|\btarget price\b|\bprice target\b|\bbuy rating\b|\bsell rating\b|\boverweight\b|\bunderweight\b|\bbrokerage"),
    ("corporate-action", r"\bdividend\b|\bbonus\b|\bsplit\b|\bbuy ?back\b|\brights issue\b|\brecord date\b|\bex-date\b"),
    ("capital", r"\bQIP\b|\bOFS\b|\bIPO\b|\bpreferential\b|\bfund ?rais|\bblock deal\b|\bbulk deal\b|\bstake sale\b|\bpledge"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bamalgamation\b|\bdemerger\b|\btakeover\b|\bJV\b|\bjoint venture\b"),
    ("order", r"\border win\b|\bbags? (?:an? )?order\b|\border worth\b|\bcontract\b|\bLoA\b|\bletter of award\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint|\bpromoter"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bCCI\b|\bUSFDA\b|\bFDA\b|\bNCLT\b|\bDGCA\b|\bTRAI\b|\bpenalty\b|\bshow.cause\b|\bED\b raid|\bincome tax\b"),
    ("risk", r"\bfraud\b|\bdefault\b|\binsolvency\b|\braid\b|\bdowngraded\b|\bASM\b|\bGSM\b|\bF&O ban\b|\bcircuit\b|\bsuspen"),
    ("macro", r"\bNifty\b|\bSensex\b|\brepo rate\b|\bMPC\b|\binflation\b|\bCPI\b|\bGDP\b|\bFII|\bFPI|\bDII|\brupee\b|\bbudget\b|\bcrude\b"),
]


# ---------------------------------------------------------------- fetching

class Fetcher:
    def __init__(self, offline=None):
        self.offline = offline
        self.last = 0.0

    def get(self, url, offline_name):
        if self.offline:
            path = os.path.join(self.offline, offline_name)
            if not os.path.exists(path):
                raise IOError("offline file missing: %s" % offline_name)
            with open(path, "rb") as fh:
                return fh.read()
        wait = PAUSE - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        finally:
            self.last = time.time()


# ---------------------------------------------------------------- inputs

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def watch_from_files(watchlist="trader/watchlist.json", portfolio="trader/portfolio.json"):
    out = []
    wl = load_json(watchlist, [])
    if isinstance(wl, dict):
        wl = wl.get("hits") or wl.get("tickers") or wl.get("symbols") or []
    for x in wl:
        s = x.get("symbol") if isinstance(x, dict) else x
        if s:
            out.append(str(s))
    pf = load_json(portfolio, {}) or {}
    for s in (pf.get("positions") or {}):
        out.append(str(s))
    return out


def clean_symbol(s):
    s = s.strip().upper()
    for suffix in (".NS", ".BO", "-EQ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def symbol_names(fetcher, state, now):
    cached = state.get("symbols") or {}
    when = state.get("symbols_at")
    if cached and when and not fetcher.offline:
        age = now - _dt.datetime.fromisoformat(when)
        if age < _dt.timedelta(days=SYMBOLS_MAX_AGE_DAYS):
            return cached
    data = fetcher.get(EQUITY_URL, "EQUITY_L.csv").decode("utf-8", "replace")
    names = {}
    for row in csv.DictReader(io.StringIO(data)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("SYMBOL"):
            names[row["SYMBOL"]] = row.get("NAME OF COMPANY", "")
    state["symbols"], state["symbols_at"] = names, now.isoformat()
    return names


def index_symbols(fetcher, state, now, wanted, errors):
    """Constituents of the requested indices, from NSE's CSVs (cached 7 days)."""
    keys = []
    for w in wanted:
        w = w.strip().upper().replace(" ", "")
        if w not in INDICES and w not in INDEX_ALIASES:
            raise SystemExit("Unknown index %s. Use NIFTY50, NIFTYNEXT50 or NIFTY100." % w)
        keys += INDEX_ALIASES.get(w, [w])
    cache = state.setdefault("indices", {})
    out = []
    for k in dict.fromkeys(keys):
        c = cache.get(k) or {}
        fresh = c.get("at") and now - _dt.datetime.fromisoformat(c["at"]) < _dt.timedelta(days=SYMBOLS_MAX_AGE_DAYS)
        if not (fresh and c.get("symbols")) or fetcher.offline:
            try:
                data = fetcher.get(INDEX_URL % INDICES[k], INDICES[k] + ".csv").decode("utf-8", "replace")
                syms = [r["Symbol"].strip() for r in csv.DictReader(io.StringIO(data)) if (r.get("Symbol") or "").strip()]
                if syms:
                    c = cache[k] = {"symbols": syms, "at": now.isoformat()}
            except (OSError, urllib.error.URLError) as e:
                errors.append("%s list: %s (%s)" % (k, e, "using cache" if c.get("symbols") else "skipped"))
        out += c.get("symbols") or []
    return out


def norm_name(name):
    n = name.lower().replace("&", "and")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp)\b", " ", n)
    return " ".join(n.split())


def short_name(name):
    """'Reliance Industries Limited' -> 'Reliance Industries' for searching."""
    n = re.sub(r"\s+(limited|ltd\.?)$", "", name.strip(), flags=re.I)
    return n.strip() or name


# ---------------------------------------------------------------- parsing

def parse_time(value):
    value = (value or "").strip()
    if not value:
        return None
    try:  # NSE: 29-Oct-2026 23:02:18, already IST
        return _dt.datetime.strptime(value, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        pass
    try:  # RFC 822, Google News
        d = email.utils.parsedate_to_datetime(value)
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_nse_rss(data, watch, names):
    """Filings for the watched symbols. Match on the PDF name (SYMBOL_...) or the company name."""
    by_name = {norm_name(names[s]): s for s in watch if names.get(s)}
    out = []
    for it in ET.fromstring(data).iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        base = link.rsplit("/", 1)[-1].upper()
        sym = next((s for s in watch if base.startswith(s + "_")), None) or by_name.get(norm_name(title))
        if not sym:
            continue
        subject = desc.split("|SUBJECT:", 1)[1].strip() if "|SUBJECT:" in desc else ""
        text = desc.split("|SUBJECT:", 1)[0].strip()
        text = re.sub(r"^.*?has informed the Exchange (about|regarding)\s*", "", text, flags=re.I) or text
        out.append({
            "kind": "filing", "symbol": sym, "source": "NSE",
            "title": subject or text[:120], "detail": text, "link": link,
            "time": parse_time(it.findtext("pubDate")),
            "important": bool(IMPORTANT_SUBJECTS.search(subject + " " + text)),
        })
    return out


def parse_gnews(data, sym):
    out = []
    for it in ET.fromstring(data).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        out.append({
            "kind": "headline", "symbol": sym, "source": src or "Google News",
            "title": title, "detail": "", "link": (it.findtext("link") or "").strip(),
            "time": parse_time(it.findtext("pubDate")), "important": False,
        })
    return out


def parse_chart(data):
    r = json.loads(data)["chart"]["result"][0]["meta"]
    price, prev = r.get("regularMarketPrice"), r.get("chartPreviousClose") or r.get("previousClose")
    if not price or not prev:
        return None
    return {"price": price, "prev": prev, "pct": (price - prev) / prev * 100}


# ---------------------------------------------------------------- logic

def tag(items):
    for it in items:
        text = it["title"] + " " + it["detail"]
        it["tags"] = [name for name, pat in KEYWORDS if re.search(pat, text, re.I)]
    return items


def fingerprint(it):
    key = it["symbol"] + "|" + (it["link"] or "") + "|" + re.sub(r"\W+", "", it["title"].lower())[:80]
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def dedupe(items):
    seen, out = set(), []
    for it in items:
        k = (it["symbol"], re.sub(r"\W+", "", it["title"].lower())[:60])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def collect(fetcher, watch, names, headlines=True, filings=True, hours=48, errors=None):
    errors = errors if errors is not None else []
    items = []
    if filings:
        try:
            items += parse_nse_rss(fetcher.get(NSE_RSS, "Online_announcements.xml"), watch, names)
        except (OSError, urllib.error.URLError, ET.ParseError) as e:
            errors.append("NSE announcements: %s" % e)
    if headlines:
        days = max(1, int(round(hours / 24.0)))
        for s in watch:
            q = '"%s" when:%dd' % (short_name(names.get(s) or s), days)
            try:
                items += parse_gnews(fetcher.get(GNEWS % urllib.parse.quote_plus(q), "gnews-%s.xml" % s), s)
            except (OSError, urllib.error.URLError, ET.ParseError) as e:
                errors.append("Google News %s: %s" % (s, e))
    return tag(dedupe(items))


def collect_moves(fetcher, watch, errors):
    moves = {}
    for s in watch:
        try:
            m = parse_chart(fetcher.get(CHART % s, "chart-%s.json" % s))
            if m:
                moves[s] = m
        except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError, TypeError) as e:
            errors.append("price %s: %s" % (s, e))
    return moves


def select(items, state, now, hours, show_all):
    seen = state.get("seen") or {}
    cutoff = now - _dt.timedelta(hours=hours)
    out = [it for it in items
           if (it["time"] is None or it["time"] >= cutoff) and (show_all or fingerprint(it) not in seen)]
    old = now.replace(year=1970)
    out.sort(key=lambda it: (not it["important"], -(it["time"] or old).timestamp()))
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    for it in items:
        seen[fingerprint(it)] = now.isoformat()
    cutoff = now - _dt.timedelta(days=KEEP_DAYS)
    state["seen"] = {k: v for k, v in seen.items() if _dt.datetime.fromisoformat(v) >= cutoff}


def ist(t):
    return t.astimezone(IST).strftime("%d-%b %H:%M") if t else "  time n/a  "


def render(items, moves, errors, watch, names, now, move_pct):
    lines = ["Indian market news, checked %s IST, tickers: %s" % (now.astimezone(IST).strftime("%d-%b-%Y %H:%M"), " ".join(watch))]
    for s in watch:
        if s not in names:
            lines.append("  ? %s is not in NSE's equity list: check the symbol" % s)
    if moves:
        lines.append("")
        shown = moves
        if len(moves) > 20:  # big lists: only the movers, biggest first
            shown = {s: m for s, m in sorted(moves.items(), key=lambda kv: -abs(kv[1]["pct"]))
                     if abs(m["pct"]) >= move_pct}
            lines.append("  %d of %d stocks moved %.0f%% or more vs prev close" % (len(shown), len(moves), move_pct))
        for s, m in shown.items():
            flag = "  MOVING" if abs(m["pct"]) >= move_pct else ""
            lines.append("  %-12s %10.2f  %+.2f%% vs prev close %.2f%s" % (s, m["price"], m["pct"], m["prev"], flag))
    lines.append("")
    if not items:
        lines.append("Nothing new.")
    for it in items:
        mark = "!" if it["important"] else " "
        kind = "FILING" if it["kind"] == "filing" else "news  "
        tags = (" [" + ", ".join(it["tags"]) + "]") if it["tags"] else ""
        lines.append("%s %s  %-10s %s  %s (%s)%s" % (mark, ist(it["time"]), it["symbol"], kind, it["title"], it["source"], tags))
        lines.append("      " + it["link"])
    quiet = [s for s in watch if not any(i["symbol"] == s for i in items)]
    if items and quiet and len(watch) > 20:
        lines.append("")
        lines.append("No new items for %d of %d stocks" % (len(quiet), len(watch)))
    elif items and quiet:
        lines.append("")
        lines.append("No new items: " + " ".join(quiet))
    for e in errors:
        lines.append("note: " + e)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE filings + Indian headlines for your tickers")
    ap.add_argument("--tickers", nargs="*", help="NSE symbols; default: trader/watchlist.json + portfolio")
    ap.add_argument("--index", nargs="+", metavar="NAME", help="add constituents: NIFTY50, NIFTYNEXT50, NIFTY100")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--state", default="trader/state/news_india.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-headlines", action="store_true", help="NSE filings only")
    ap.add_argument("--no-filings", action="store_true", help="headlines only")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT)
    ap.add_argument("--max-per-ticker", type=int, default=15, help="cap headlines per ticker")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    now = _dt.datetime.fromisoformat(a.now) if a.now else _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    fetcher = Fetcher(a.offline)
    state = load_json(a.state, {}) or {}
    errors = []
    picked = list(a.tickers or [])
    if a.index:
        picked += index_symbols(fetcher, state, now, a.index, errors)
    elif not picked:
        picked = watch_from_files(a.watchlist, a.portfolio)
    watch = list(dict.fromkeys(clean_symbol(s) for s in picked))
    if not watch:
        print("No tickers. Pass --tickers RELIANCE TCS ..., --index NIFTY50, or fill trader/watchlist.json.", file=sys.stderr)
        return 2
    if len(watch) > 20 and not a.no_headlines:
        print("Checking headlines for %d stocks takes about %d s (one request a second). "
              "--no-headlines --no-moves is fast." % (len(watch), len(watch) * 2), file=sys.stderr)
    try:
        names = symbol_names(fetcher, state, now)
    except (OSError, urllib.error.URLError) as e:
        names = state.get("symbols") or {}
        errors.append("NSE symbol list: %s (using cache: %d symbols)" % (e, len(names)))

    items = collect(fetcher, watch, names, not a.no_headlines, not a.no_filings, a.hours, errors)
    items = select(items, state, now, a.hours, a.all)
    capped, count = [], {}
    for it in items:
        if it["kind"] == "headline":
            count[it["symbol"]] = count.get(it["symbol"], 0) + 1
            if count[it["symbol"]] > a.max_per_ticker:
                continue
        capped.append(it)
    items = capped
    moves = {} if a.no_moves else collect_moves(fetcher, watch, errors)

    if a.json:
        out = [dict(it, time=it["time"].isoformat() if it["time"] else None, id=fingerprint(it)) for it in items]
        print(json.dumps({"checked": now.isoformat(), "tickers": watch, "moves": moves,
                          "items": out, "errors": errors}, indent=2))
    else:
        print(render(items, moves, errors, watch, names, now, a.move_pct))

    if not a.dry_run:
        remember(items, state, now)
        os.makedirs(os.path.dirname(a.state) or ".", exist_ok=True)
        tmp = a.state + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, a.state)
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())

"""Results-day lookup for signal stocks (Google News, India edition). Standard library only.

results_dates(symbols, now, state_path) -> {symbol: {"date": "YYYY-MM-DD", "kind": "due" | "out",
                                                     "title": headline}}
Only headlines that name the company and talk about its results are used:
"to announce Q2 results today", "results on November 5", "Q2 preview",
"Q2 profit rises 32%". A date is kept when it falls between yesterday and
3 days ahead. Answers are cached for 12 hours in the state file.
"""

import datetime as _dt
import email.utils
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
UA = "Mozilla/5.0 (compatible; trader-bos-india/1.0)"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
NAMES_FILE = "trader/state/news_india.json"   # symbol -> company name, kept by trader-news-india
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"], 1)}
RESULT = re.compile(r"\b(results?|earnings|q[1-4]\s*(?:fy)?\d*|quarterly|profit|net profit|pat)\b", re.I)
DUE = re.compile(r"\b(to announce|to report|to declare|results? (?:today|tomorrow|on|date|due)|preview|"
                 r"board meeting|ahead of (?:q[1-4]|results?)|expectations?|what to expect|due today|likely|expected|"
                 r"estimates? (?:show|see)|may|could|seen|poll|brokerages? (?:see|expect))\b", re.I)
OUT = re.compile(r"\b(profit|pat|revenue|ebitda|net income)\b.*\b(rises?|rose|jumps?|falls?|fell|dips?|grows?|"
                 r"up|down|surges?|declines?|beats?|miss(?:es)?)\b", re.I)
DATE = re.compile(r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|"
                  r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?)\b", re.I)


def _names():
    try:
        with open(NAMES_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("symbols") or {}
    except (OSError, ValueError):
        return {}


# names whose headlines use another form, or whose short form would match other companies
NAME_FIX = {"HAL": "Hindustan Aeronautics", "HINDUNILVR": "Hindustan Unilever", "HINDZINC": "Hindustan Zinc",
            "SOLARINDS": "Solar Industries", "M&M": "Mahindra & Mahindra", "BEL": "Bharat Electronics",
            "BPCL": "Bharat Petroleum", "IOC": "Indian Oil", "ONGC": "ONGC", "SBIN": "SBI", "LT": "Larsen",
            "TMPV": "Tata Motors", "TMCV": "Tata Motors", "INDIGO": "IndiGo", "ETERNAL": "Eternal Ltd",
            "TRENT": "Trent Ltd", "BSE": "BSE Ltd", "IRFC": "IRFC", "PFC": "Power Finance", "LTM": "LTIMindtree"}


def _short(name, sym):
    if sym in NAME_FIX:
        return NAME_FIX[sym]
    if not name:
        return sym
    # drop only trailing legal words: "Titan Company Limited" -> "Titan", "Solar Industries India" stays in NAME_FIX
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"[\s.,]+(limited|ltd\.?|company|corporation|india)$", "", name.strip(), flags=re.I)
    words = name.strip(" .&").split()
    # headlines use the first words: "Apollo Hospitals Enterprise" -> "Apollo Hospitals"
    keep = 3 if len(words) > 2 and words[1] == "&" else 2
    return " ".join(words[:keep]) or sym


# other companies that share the name
NOT_THIS = {"TITAN": r"Titan (?:America|Machinery|Pharma|Securities|Intech|Biotech)", "TRENT": r"Severn Trent",
            "BSE": r"\bBSE (?:Sensex|SME|listed)", "ETERNAL": r"Eternal (?:Hospitality|Life)"}


def _event_date(title, pub):
    """Date the headline points at, plus 'due' or 'out'."""
    low = title.lower()
    d = pub.astimezone(IST).date()
    if OUT.search(title) and not DUE.search(title):
        return d, "out"
    m = DATE.search(title)
    if m:
        day = int(m.group(1) or m.group(4))
        mon = MONTHS[(m.group(2) or m.group(3)).lower()[:3]]
        try:
            cand = _dt.date(d.year, mon, day)
            if (cand - d).days < -180:
                cand = _dt.date(d.year + 1, mon, day)
            return cand, "due"
        except ValueError:
            pass
    if "tomorrow" in low:
        return d + _dt.timedelta(days=1), "due"
    if DUE.search(title):
        return d, "due"
    return None, None


def _lookup(sym, name, now):
    q = '"%s" results when:7d' % name
    req = urllib.request.Request(GNEWS % urllib.parse.quote(q), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    today = now.date()
    best = None
    key = re.compile(r"\b%s\b" % re.escape(re.sub(r"\s+(Ltd)$", "", name)), re.I)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not key.search(title) or not RESULT.search(title) or (
                sym in NOT_THIS and re.search(NOT_THIS[sym], title, re.I)):
            continue
        try:
            pub = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        d, kind = _event_date(title, pub)
        if not d or not (-1 <= (d - today).days <= 3):
            continue
        if best is None or (kind == "out", d) > (best["kind"] == "out", best["date"]):
            best = {"date": d, "kind": kind, "title": title.rsplit(" - ", 1)[0]}
    return best


def results_dates(symbols, now, state_path, progress=lambda m: None):
    try:
        with open(state_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    names, out, todo = _names(), {}, []
    for sym in symbols:
        c = cache.get(sym)
        if c and (now - _dt.datetime.fromisoformat(c["checked"])).total_seconds() < 12 * 3600:
            if c.get("date"):
                out[sym] = c
        else:
            todo.append(sym)
    if todo:
        progress("Checking results dates for %d stocks (~%d s)..." % (len(todo), len(todo)))
    for sym in todo:
        try:
            hit = _lookup(sym, _short(names.get(sym), sym), now)
        except Exception:  # noqa: BLE001 - a failed lookup just means no warning
            hit = None
        entry = {"checked": now.isoformat()}
        if hit:
            entry.update(date=hit["date"].isoformat(), kind=hit["kind"], title=hit["title"])
            out[sym] = entry
        cache[sym] = entry
        time.sleep(0.8)
    try:
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=1)
    except OSError:
        pass
    return out

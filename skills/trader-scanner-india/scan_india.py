#!/usr/bin/env python3
"""Chart scanner for Indian stocks (NSE). Standard library only.

    python3 scan_india.py daily                          # Nifty 500, daily setups -> trader/watchlist.json
    python3 scan_india.py daily --index NIFTY100
    python3 scan_india.py daily --symbols RELIANCE,TCS,COALINDIA
    python3 scan_india.py orb                            # after 9:35 IST: opening-range breakouts
    python3 scan_india.py orb --index NIFTY50 --at 10:30 --or-minutes 15

Universe (--index, default NIFTY500): NIFTY50, NIFTYNEXT50, NIFTY100,
NIFTY500, MIDCAP150, SMALLCAP250, from NSE's published constituent CSVs
(cached 7 days), or --symbols / --watchlist.

daily   Three months of daily CLOSES (Yahoo spark, 20 symbols a request).
        Today's bar is dropped until 15:30 IST. Liquidity: last price >=
        --min-price (Rs 20) and today's turnover (price x volume) >=
        --min-turnover-cr (Rs 5 crore). Setups:
          breakout_20d     last close above every close of the 20 before it
          breakdown_20d    last close below every close of the 20 before it
          bull_flag        up > 10 % over the 10 sessions before the last 5,
                           then the last 5 closes inside a 5 % range
          reclaim_ma20     closed under the 20-day average, then above it
          lost_ma20        closed above the 20-day average, then under it
          oversold         RSI 14 (Wilder) under 30
          oversold_bounce  RSI 14 under 30 yesterday, closed up today
          overbought       RSI 14 over 70

orb     Opening-range breakouts on 5-minute bars. Range = the first
        --or-minutes (15) from 9:15 IST. Stage 1: spark closes for every
        symbol; a candidate has a completed bar after the range closing
        beyond the range's highest (or lowest) close. Stage 2: the v8 chart
        (real highs and lows) for up to --max-confirm candidates, most
        traded first. orb_up = first completed bar to CLOSE above the range
        high; orb_down = first to close below the range low. Every range bar
        must be there; after it, Yahoo drops the odd bar (always 15:20), so
        up to --max-missing (default 10 % of the bars so far) may be missing.

Times are IST. Yahoo's endpoints are free, unofficial and can lag or
rate-limit; partial results say so. There is no holiday table: when the
data has no bar for today on a weekday, the scan says so (holiday or lag).

A scan is a list of charts that match a rule, not a list of stocks to buy.
Exit code 0 when the scan found something, 1 when not, 2 on bad input.
"""

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; trader-scanner-india/1.0)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/%s.csv"
INDICES = {"NIFTY50": "ind_nifty50list", "NIFTYNEXT50": "ind_niftynext50list",
           "NIFTY500": "ind_nifty500list", "MIDCAP150": "ind_niftymidcap150list",
           "SMALLCAP250": "ind_niftysmallcap250list"}
ALIASES = {"NIFTY": ["NIFTY50"], "NEXT50": ["NIFTYNEXT50"], "NIFTYJR": ["NIFTYNEXT50"],
           "NIFTY100": ["NIFTY50", "NIFTYNEXT50"], "MIDCAP": ["MIDCAP150"], "SMALLCAP": ["SMALLCAP250"]}
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
OPEN, CLOSE = _dt.time(9, 15), _dt.time(15, 30)
BAR_MIN = 5
SPARK_MAX = 20
PAUSE = 0.4
BACKOFF = 5.0
CACHE_DAYS = 7
MIN_DAILY_BARS = 30
CRORE = 1e7
NOTE = "A scan is a list of charts that match a rule, not a list of stocks to buy."


class ScanError(Exception):
    pass


# ---------------------------------------------------------------- network

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_get(path):
    """query2 first, query1 on a 429/5xx, one retry after a pause on a 429."""
    last = None
    for attempt in range(2):
        for host in YAHOO_HOSTS:
            try:
                return json.loads(http_get(host + path))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    return None
                if e.code != 429 and e.code < 500:
                    raise ScanError("Yahoo answered HTTP %d" % e.code)
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
        time.sleep(BACKOFF)
    raise ScanError("Yahoo unreachable: %s" % last)


def to_yahoo(sym):
    return urllib.parse.quote(sym + ".NS", safe=".-")  # M&M -> M%26M.NS


def from_yahoo(sym):
    return sym[:-3] if sym.endswith(".NS") else sym


# ---------------------------------------------------------------- universe

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


def clean_symbol(s):
    s = s.strip().upper()
    for suffix in (".NS", ".BO", "-EQ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def index_symbols(names, state, now, notes):
    keys = []
    for n in names:
        n = n.strip().upper().replace(" ", "").replace("_", "")
        if n not in INDICES and n not in ALIASES:
            raise ScanError("unknown index %s. Use one of: %s, NIFTY100"
                            % (n, ", ".join(sorted(INDICES))))
        keys += ALIASES.get(n, [n])
    cache = state.setdefault("indices", {})
    out = []
    for k in dict.fromkeys(keys):
        c = cache.get(k) or {}
        fresh = c.get("at") and now - _dt.datetime.fromisoformat(c["at"]) < _dt.timedelta(days=CACHE_DAYS)
        if not (fresh and c.get("symbols")):
            try:
                rows = csv.DictReader(io.StringIO(http_get(INDEX_URL % INDICES[k])))
                syms = [r["Symbol"].strip() for r in rows if (r.get("Symbol") or "").strip()]
                if syms:
                    c = cache[k] = {"symbols": syms, "at": now.isoformat()}
            except (OSError, urllib.error.URLError) as e:
                notes.append("%s list: %s (%s)" % (k, e, "using cache" if c.get("symbols") else "skipped"))
        out += c.get("symbols") or []
    return out


def symbols_from_watchlist(path):
    doc = load_json(path)
    if doc is None:
        raise ScanError("cannot read %s" % path)
    if isinstance(doc, dict):
        doc = doc.get("hits") or doc.get("symbols") or doc.get("tickers") or []
    return [x.get("symbol") if isinstance(x, dict) else x for x in doc if x]


# ---------------------------------------------------------------- data

def series_from_result(res):
    """A Yahoo chart result (v8 or one spark entry) -> plain lists."""
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    t = res.get("timestamp") or []
    n = len(t)
    pick = lambda k: (q.get(k) or [None] * n)[:n]
    return {"t": t, "o": pick("open"), "h": pick("high"), "l": pick("low"),
            "c": pick("close"), "v": pick("volume"), "meta": res.get("meta") or {}}


def fetch_spark(symbols, rng, interval, pause, progress):
    data, failed = {}, []
    batches = [symbols[i:i + SPARK_MAX] for i in range(0, len(symbols), SPARK_MAX)]
    for k, batch in enumerate(batches):
        path = "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (
            ",".join(to_yahoo(s) for s in batch), rng, interval)
        try:
            doc = yahoo_get(path) or {}
            got = set()
            for r in ((doc.get("spark") or {}).get("result") or []):
                resp = (r.get("response") or [None])[0]
                if resp:
                    sym = from_yahoo(r.get("symbol", ""))
                    data[sym] = series_from_result(resp)
                    got.add(sym)
            failed += [s for s in batch if s not in got]
        except ScanError as e:
            failed += batch
            progress("  batch %d failed: %s" % (k + 1, e))
        if (k + 1) % 5 == 0 or k + 1 == len(batches):
            progress("  %d of %d requests" % (k + 1, len(batches)))
        time.sleep(pause)
    return data, failed


def fetch_chart(sym, rng, interval):
    doc = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s" % (to_yahoo(sym), rng, interval))
    res = ((doc or {}).get("chart") or {}).get("result") or []
    return series_from_result(res[0]) if res else None


def ist(ts):
    return _dt.datetime.fromtimestamp(int(ts), IST)


# ---------------------------------------------------------------- daily setups

def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def daily_closes(series, now):
    """[(date, close)] of complete daily bars; today's bar only after 15:30 IST."""
    today_done = now.time() >= CLOSE
    out = {}
    for ts, c in zip(series["t"], series["c"]):
        if c is None:
            continue
        d = ist(ts).date()
        if d > now.date() or (d == now.date() and not today_done):
            continue
        out[d] = float(c)
    return sorted(out.items())


def find_setups(c):
    last = c[-1]
    hi20, lo20 = max(c[-21:-1]), min(c[-21:-1])
    ma20, ma20_prev = sum(c[-20:]) / 20.0, sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r, r_prev = rsi(c), rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if last < lo20:
        tags.append("breakdown_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if c[-2] > ma20_prev and last < ma20:
        tags.append("lost_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    if r is not None and r > 70:
        tags.append("overbought")
    return tags, {"rsi": r, "high20": hi20, "low20": lo20, "ma20": ma20,
                  "change_pct": (last / c[-2] - 1) * 100}


def scan_daily(data, symbols, now, min_price, min_turnover):
    hits = []
    counts = {"requested": len(symbols), "fetched": 0, "illiquid": 0, "short": 0, "scanned": 0}
    dates = {}
    for sym in symbols:
        s = data.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        bars = daily_closes(s, now)
        meta = s["meta"]
        price = meta.get("regularMarketPrice") or (bars[-1][1] if bars else None)
        vol = meta.get("regularMarketVolume")
        turnover = price * vol if price and vol else None
        if price is None or price < min_price or (min_turnover > 0 and (turnover or 0) < min_turnover):
            counts["illiquid"] += 1
            continue
        if len(bars) < MIN_DAILY_BARS:
            counts["short"] += 1
            continue
        counts["scanned"] += 1
        dates[bars[-1][0]] = dates.get(bars[-1][0], 0) + 1
        closes = [c for _, c in bars]
        tags, nums = find_setups(closes)
        if tags:
            hits.append({"symbol": sym, "setups": tags, "price": round(closes[-1], 2),
                         "change_pct": round(nums["change_pct"], 2), "rsi": round(nums["rsi"], 1),
                         "close_date": bars[-1][0].isoformat(),
                         "turnover_cr": round(turnover / CRORE, 1) if turnover else None})
    hits.sort(key=lambda h: (-(h["turnover_cr"] or 0), h["symbol"]))
    last_date = max(dates, key=lambda d: (dates[d], d)) if dates else None
    return hits, counts, last_date


# ---------------------------------------------------------------- opening range

def session_bars(series, day, cutoff):
    """Completed 5-minute bars of `day` from 9:15 up to `cutoff` (a time), keyed by slot."""
    bars = {}
    for i, ts in enumerate(series["t"]):
        t = ist(ts)
        if t.date() != day or series["c"][i] is None:
            continue
        mins = (t.hour * 60 + t.minute) - (OPEN.hour * 60 + OPEN.minute)
        if mins < 0 or mins % BAR_MIN or t.second:
            continue  # pre-open or the live tick
        end = t + _dt.timedelta(minutes=BAR_MIN)
        if end.time() > cutoff or end.time() > CLOSE:
            continue
        k = mins // BAR_MIN
        bars[k] = {"k": k, "end": end, "c": series["c"][i],
                   "h": series["h"][i] if series["h"][i] is not None else series["c"][i],
                   "l": series["l"][i] if series["l"][i] is not None else series["c"][i],
                   "v": series["v"][i] or 0}
    return bars


def orb_check(bars, n_range, use_hl):
    """(range_high, range_low, up_hit, down_hit); hits are the first bar to close beyond the range."""
    if not all(k in bars for k in range(n_range)):
        return None
    rng = [bars[k] for k in range(n_range)]
    hi = max(b["h"] if use_hl else b["c"] for b in rng)
    lo = min(b["l"] if use_hl else b["c"] for b in rng)
    up = down = None
    for k in sorted(k for k in bars if k >= n_range):
        b = bars[k]
        if up is None and b["c"] > hi:
            up = b
        if down is None and b["c"] < lo:
            down = b
    return hi, lo, up, down


def missing(bars, cutoff_slots):
    return sum(1 for k in range(cutoff_slots) if k not in bars)


def scan_orb(stage1, symbols, day, cutoff, or_minutes, min_price, max_missing, max_confirm,
             confirm, progress):
    n_range = or_minutes // BAR_MIN
    slots = ((cutoff.hour * 60 + cutoff.minute) - (OPEN.hour * 60 + OPEN.minute)) // BAR_MIN
    counts = {"requested": len(symbols), "fetched": 0, "gappy": 0, "cheap": 0,
              "candidates": 0, "confirmed": 0, "hits": 0}
    cands = []
    for sym in symbols:
        s = stage1.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        bars = session_bars(s, day, cutoff)
        allowed = max_missing if max_missing is not None else max(1, slots // 10)
        if missing(bars, slots) > allowed:
            counts["gappy"] += 1
            continue
        last = bars[max(bars)]["c"] if bars else None
        if last is None or last < min_price:
            counts["cheap"] += 1
            continue
        r = orb_check(bars, n_range, use_hl=False)
        if r and (r[2] or r[3]):
            traded = sum(b["c"] * b["v"] for b in bars.values())
            cands.append((traded, sym))
    cands.sort(reverse=True)
    counts["candidates"] = len(cands)
    if len(cands) > max_confirm:
        progress("  %d candidates, confirming the %d most traded" % (len(cands), max_confirm))
    hits = []
    for traded, sym in cands[:max_confirm]:
        try:
            s = confirm(sym)
        except ScanError as e:
            progress("  %s: %s" % (sym, e))
            continue
        if not s:
            continue
        counts["confirmed"] += 1
        bars = session_bars(s, day, cutoff)
        r = orb_check(bars, n_range, use_hl=True)
        if not r:
            continue
        hi, lo, up, down = r
        last = bars[max(bars)]
        for side, b in (("orb_up", up), ("orb_down", down)):
            if b:
                hits.append({"symbol": sym, "setups": [side], "range_high": round(hi, 2),
                             "range_low": round(lo, 2), "range_pct": round((hi - lo) / lo * 100, 2),
                             "trigger_time": b["end"].strftime("%H:%M"), "trigger_close": round(b["c"], 2),
                             "price": round(last["c"], 2),
                             "turnover_cr": round(sum(x["c"] * x["v"] for x in bars.values()) / CRORE, 1)})
    hits.sort(key=lambda h: (h["trigger_time"], -(h["turnover_cr"] or 0)))
    counts["hits"] = len(hits)
    return hits, counts


# ---------------------------------------------------------------- commands

def parse_now(text):
    if not text:
        return _dt.datetime.now(IST).replace(microsecond=0)
    d = _dt.datetime.fromisoformat(text)
    return d.astimezone(IST) if d.tzinfo else d.replace(tzinfo=IST)


def read_universe(a, state, now, notes):
    if a.symbols:
        syms = re.split(r"[,\s]+", a.symbols)
    elif a.watchlist:
        syms = symbols_from_watchlist(a.watchlist)
    else:
        syms = index_symbols(a.index or ["NIFTY500"], state, now, notes)
    out = list(dict.fromkeys(clean_symbol(s) for s in syms if s and s.strip()))
    if a.limit:
        out = out[:a.limit]
    if not out:
        raise ScanError("no symbols to scan")
    return out


def money(x):
    return "Rs %s" % format(round(x, 2), ",")


def pick_source(a, now):
    """(source, kite client or None, note or None). auto = Kite when today's token is in the config."""
    if a.source == "yahoo":
        return "yahoo", None, None
    import kite_data
    if a.source == "auto" and not kite_data.token_ready(a.kite_config, now.date()):
        note = None
        if os.path.exists(a.kite_config):
            note = "Kite token is not from today: used Yahoo. Run kite_login.py for Kite data."
        return "yahoo", None, note
    try:
        return "kite", kite_data.Kite(a.kite_config), None
    except kite_data.KiteError as e:
        raise ScanError(str(e))


def kite_fetch(kite, symbols, interval, frm, to, progress):
    import kite_data
    progress("Kite %s candles for %d stocks (~%d s)..." % (interval, len(symbols), len(symbols) * kite_data.MIN_GAP + 2))
    try:
        return kite_data.fetch_many(kite, symbols, interval, frm, to, progress)
    except kite_data.KiteError as e:
        raise ScanError(str(e))


def cmd_daily(a, now, symbols, progress):
    source, kite = a.source_pick
    if source == "kite":
        data, failed = kite_fetch(kite, symbols, "day", now - _dt.timedelta(days=130), now, progress)
    else:
        progress("Daily closes for %d stocks (%d requests)..." % (len(symbols), -(-len(symbols) // SPARK_MAX)))
        data, failed = fetch_spark(symbols, "3mo", "1d", a.pause, progress)
    hits, counts, last_date = scan_daily(data, symbols, now, a.min_price, a.min_turnover_cr * CRORE)
    notes = []
    if now.weekday() < 5 and now.time() >= CLOSE and last_date and last_date < now.date():
        notes.append("no daily bar for today yet: NSE holiday or data lag")
    lines = ["Daily scan, %s IST, closes through %s (%s, daily closes only)." % (
        now.strftime("%a %d-%b-%Y %H:%M"), last_date.isoformat() if last_date else "n/a",
        "Zerodha Kite" if source == "kite" else "Yahoo"),
        "%d requested, %d fetched, %d failed, %d below price/turnover floor, %d too short, %d scanned, %d hits." % (
            counts["requested"], counts["fetched"], len(failed), counts["illiquid"], counts["short"],
            counts["scanned"], len(hits))]
    by_setup = {}
    for h in hits:
        for t in h["setups"]:
            by_setup.setdefault(t, []).append(h)
    for t in ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold_bounce", "oversold",
              "overbought", "lost_ma20", "breakdown_20d"):
        if t in by_setup:
            lines.append("")
            lines.append("%s (%d)" % (t, len(by_setup[t])))
            for h in by_setup[t][:a.show]:
                lines.append("  %-12s %12s  %+6.2f%%  RSI %5.1f  turnover %s cr" % (
                    h["symbol"], money(h["price"]), h["change_pct"], h["rsi"], h["turnover_cr"]))
            if len(by_setup[t]) > a.show:
                lines.append("  ... %d more (--show N)" % (len(by_setup[t]) - a.show))
    return hits, counts, failed, lines, notes


def cmd_orb(a, now, symbols, progress):
    cutoff = _dt.time(*map(int, a.at.split(":"))) if a.at else now.time()
    day = _dt.date.fromisoformat(a.day) if a.day else now.date()
    first = (_dt.datetime.combine(day, OPEN) + _dt.timedelta(minutes=a.or_minutes + BAR_MIN)).time()
    if not a.day and (now.weekday() >= 5 or cutoff < first):
        raise ScanError("too early or not a trading day: the first breakout bar completes at %s IST. "
                        "Use --day YYYY-MM-DD for a past session." % first.strftime("%H:%M"))
    if cutoff > CLOSE:
        cutoff = CLOSE
    source, kite = a.source_pick
    if source == "kite":
        frm = _dt.datetime.combine(day, OPEN)
        stage1, failed = kite_fetch(kite, symbols, "5minute", frm, _dt.datetime.combine(day, CLOSE), progress)
        confirm = stage1.get  # Kite candles already carry real highs and lows
        max_confirm = len(symbols)
    else:
        rng = "1d" if day == now.date() else "5d"
        progress("5-minute bars for %d stocks (%d requests)..." % (len(symbols), -(-len(symbols) // SPARK_MAX)))
        stage1, failed = fetch_spark(symbols, rng, "5m", a.pause, progress)
        max_confirm = a.max_confirm

        def confirm(sym):
            time.sleep(a.pause)
            return fetch_chart(sym, rng, "5m")

    hits, counts = scan_orb(stage1, symbols, day, cutoff, a.or_minutes, a.min_price,
                            a.max_missing, max_confirm, confirm, progress)
    notes = []
    if counts["fetched"] and counts["gappy"] == counts["fetched"]:
        notes.append("no stock had bars for %s: NSE holiday, weekend or data lag" % day.isoformat())
    lines = ["Opening-range scan (%s), %s, range 9:15-%s IST, bars through %s IST." % (
        "Zerodha Kite" if source == "kite" else "Yahoo",
        day.strftime("%a %d-%b-%Y"),
        (_dt.datetime.combine(day, OPEN) + _dt.timedelta(minutes=a.or_minutes)).strftime("%H:%M"),
        cutoff.strftime("%H:%M")),
        "%d requested, %d fetched, %d failed, %d gappy, %d under price floor, %d candidates, %d confirmed, %d hits." % (
            counts["requested"], counts["fetched"], len(failed), counts["gappy"], counts["cheap"],
            counts["candidates"], counts["confirmed"], counts["hits"])]
    for side in ("orb_up", "orb_down"):
        rows = [h for h in hits if side in h["setups"]]
        if rows:
            lines.append("")
            lines.append("%s (%d)" % (side, len(rows)))
            for h in rows[:a.show]:
                lines.append("  %-12s %s  range %s-%s (%.2f%%)  close %s  now %s  turnover %s cr" % (
                    h["symbol"], h["trigger_time"], money(h["range_low"]), money(h["range_high"]),
                    h["range_pct"], money(h["trigger_close"]), money(h["price"]), h["turnover_cr"]))
            if len(rows) > a.show:
                lines.append("  ... %d more (--show N)" % (len(rows) - a.show))
    return hits, counts, failed, lines, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE chart scanner: daily setups and opening-range breakouts")
    ap.add_argument("mode", choices=["daily", "orb"])
    ap.add_argument("--index", nargs="+", metavar="NAME",
                    help="NIFTY50 NIFTYNEXT50 NIFTY100 NIFTY500 MIDCAP150 SMALLCAP250 (default NIFTY500)")
    ap.add_argument("--symbols", help="comma separated NSE symbols instead of an index")
    ap.add_argument("--watchlist", help="scan the symbols in this JSON file")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-price", type=float, default=20.0, help="rupees (default 20)")
    ap.add_argument("--min-turnover-cr", type=float, default=5.0, help="daily: today's turnover floor, crore")
    ap.add_argument("--or-minutes", type=int, default=15, choices=[5, 10, 15, 30, 60])
    ap.add_argument("--at", help="orb: cut the clock at HH:MM IST")
    ap.add_argument("--day", help="orb: a past session YYYY-MM-DD (last 5 days)")
    ap.add_argument("--max-missing", type=int, help="orb: allowed missing 5-minute bars (default 10%% of the session so far; the range bars must all be there)")
    ap.add_argument("--max-confirm", type=int, default=150)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--source", choices=["auto", "kite", "yahoo"], default="auto",
                    help="auto = Zerodha Kite when today's token exists, else Yahoo")
    ap.add_argument("--kite-config", default=os.path.expanduser("~/.config/trader-india/kite.json"))
    ap.add_argument("--now", help="ISO time (IST if no zone), for reproducible runs")
    ap.add_argument("--out", default="trader/watchlist.json")
    ap.add_argument("--state", default="trader/state/scanner_india.json")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    progress = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    now = parse_now(a.now)
    state = load_json(a.state, {}) or {}
    notes = []
    try:
        symbols = read_universe(a, state, now, notes)
        if a.mode == "orb" and a.at is None and a.day:
            a.at = "15:30"
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # kite_data.py lives here
        source, kite, note = pick_source(a, now)
        a.source_pick = (source, kite)
        if note:
            notes.append(note)
        run = cmd_daily if a.mode == "daily" else cmd_orb
        hits, counts, failed, lines, more = run(a, now, symbols, progress)
    except ScanError as e:
        print(str(e))
        return 2 if "unknown index" in str(e) or "no symbols" in str(e) else 1
    notes += more
    write_json(a.state, state)

    doc = {"mode": a.mode, "as_of": now.isoformat(), "market": "NSE",
           "universe": " ".join(a.index or []) or ("symbols" if a.symbols else a.watchlist or "NIFTY500"),
           "scanned": counts, "failed": failed, "hits": hits, "note": NOTE}
    if not a.no_write:
        write_json(a.out, doc)
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("\n".join(lines))
        for n in notes:
            print("note: " + n)
        if failed:
            print("failed: " + " ".join(failed[:20]) + (" ..." if len(failed) > 20 else ""))
        if not a.no_write:
            print("Wrote %d hits to %s." % (len(hits), a.out))
        print(NOTE)
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())

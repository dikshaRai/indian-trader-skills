#!/usr/bin/env python3
"""Scheduled runner for the Indian trader skills. Standard library only.

Runs the installed skills, merges scanner hits with their news, writes a
dated Markdown report and shows a Mac notification. It reads charts and
news only: it never logs in to Zerodha and never places orders.

    python3 trader_day.py reminder     # 8:35  notify if today's Zerodha login is missing
    python3 trader_day.py premarket    # 8:45  Nifty 50 news + Nifty 100 daily setups
    python3 trader_day.py orb          # 9:40+ opening-range hits + news on each hit
    python3 trader_day.py evening      # 22:15 the day's NSE filings before the feed resets

Reports: <data dir>/trader/reports/YYYY-MM-DD/HHMM-<mode>.md, and
trader/reports/latest.md is always the newest. The data dir is where
trader/watchlist.json lives (default: the folder this was installed for,
see --data).
"""

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
SKILLS = os.path.expanduser("~/.claude/skills")
SCAN = os.path.join(SKILLS, "trader-scanner-india", "scan_india.py")
NEWS = os.path.join(SKILLS, "trader-news-india", "news_india.py")
LOGIN = os.path.join(SKILLS, "trader-scanner-india", "kite_login.py")
DEFAULT_DATA = os.environ.get("TRADER_DATA_DIR", os.getcwd())


def run(args, data, timeout=900):
    """Run a skill script with python3 -I in the data dir; return (exit code, stdout)."""
    try:
        p = subprocess.run([sys.executable, "-I"] + args, cwd=data, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


def run_json(args, data):
    code, out = run(args + ["--json"], data)
    try:
        return json.loads(out)
    except ValueError:
        return None


def notify(title, text):
    text = text.replace('"', "'")[:230]
    subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s"' % (text, title.replace('"', "'"))],
                   capture_output=True)


def token_ok(data):
    code, _ = run([LOGIN, "--check"], data, timeout=30)
    return code == 0


def news_by_symbol(doc):
    """symbol -> {net, pos, neg, filings[], top[]} from news_india --json."""
    out = {}
    for it in (doc or {}).get("items", []):
        s = out.setdefault(it["symbol"], {"net": 0, "pos": 0, "neg": 0, "filings": [], "top": []})
        if it["kind"] == "filing":
            s["filings"].append(it)
            continue
        s["net"] += it.get("sentiment_score", 0)
        s["pos"] += it.get("sentiment") == "positive"
        s["neg"] += it.get("sentiment") == "negative"
        if it.get("sentiment") != "neutral" and len(s["top"]) < 2:
            s["top"].append(it)
    return out


def mood(n):
    return "▲ positive" if n > 0 else "▼ negative" if n < 0 else "· none/mixed"


def md_link(title, url):
    return "[%s](%s)" % (title.replace("[", "(").replace("]", ")").replace("|", "/")[:110], url)


def write_report(data, mode, now, lines):
    day = os.path.join(data, "trader", "reports", now.strftime("%Y-%m-%d"))
    os.makedirs(day, exist_ok=True)
    path = os.path.join(day, "%s-%s.md" % (now.strftime("%H%M"), mode))
    text = "\n".join(lines) + "\n"
    for p in (path, os.path.join(data, "trader", "reports", "latest.md")):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path


FOOT = ["", "---", "_Charts that match a rule and published news, not a list of stocks to buy. "
        "Check the chart, the story and your stop before any trade; place orders yourself in Kite._"]


# ---------------------------------------------------------------- modes

def do_reminder(a, now):
    if token_ok(a.data):
        return 0
    notify("Zerodha login needed", "Run kite_login.py before 9:15 so the scans use Kite data.")
    return 0


def do_premarket(a, now):
    lines = ["# Pre-market brief, %s IST" % now.strftime("%a %d-%b-%Y %H:%M"), ""]
    if not token_ok(a.data):
        lines += ["> ⚠️ No Zerodha token for today: scans use Yahoo. Run `kite_login.py`.", ""]
    news = run_json([NEWS, "--index", "NIFTY50", "--hours", "18", "--max-per-ticker", "8",
                     "--no-moves", "--all", "--dry-run"], a.data)
    by = news_by_symbol(news)
    lines += ["## News sentiment, Nifty 50 (since yesterday evening)", "",
              "> NSE's filing feed resets at midnight: last evening's filings are in the 22:15 report.", "",
              "| Stock | Net | ▲ | ▼ | Strongest headline |", "|---|---|---|---|---|"]
    for s, v in sorted(by.items(), key=lambda kv: kv[1]["net"]):
        if v["net"] or v["filings"]:
            top = v["top"][0] if v["top"] else (v["filings"][0] if v["filings"] else None)
            lines.append("| %s | %+d | %d | %d | %s |" % (s, v["net"], v["pos"], v["neg"],
                                                       md_link(top["title"], top["link"]) if top else ""))
    daily = run_json([SCAN, "daily", "--index", "NIFTY100", "--no-write", "--quiet"], a.data)
    lines += ["", "## Daily setups, Nifty 100 (closes through yesterday)", ""]
    groups = {}
    for h in (daily or {}).get("hits", []):
        for t in h["setups"]:
            groups.setdefault(t, []).append(h["symbol"])
    for t, syms in groups.items():
        lines.append("- **%s** (%d): %s" % (t, len(syms), ", ".join(syms[:15])))
    if not groups:
        lines.append("- none, or the scan could not run")
    path = write_report(a.data, "premarket", now, lines + FOOT)
    worst = sorted(((v["net"], s) for s, v in by.items()))[:2]
    best = sorted(((v["net"], s) for s, v in by.items()), reverse=True)[:2]
    notify("Pre-market brief ready", "Positive: %s. Negative: %s. %d daily setups." % (
        ", ".join(s for n, s in best if n > 0) or "none", ", ".join(s for n, s in worst if n < 0) or "none",
        sum(len(v) for v in groups.values())))
    print(path)
    return 0


def do_orb(a, now):
    scan = run_json([SCAN, "orb", "--index", a.index, "--quiet"], a.data)  # also writes trader/watchlist.json
    if not scan:
        notify("ORB scan failed", "The opening-range scan did not run (too early, holiday or no data).")
        return 1
    hits = scan.get("hits", [])
    syms = list(dict.fromkeys(h["symbol"] for h in hits))
    news = run_json([NEWS, "--tickers"] + syms + ["--hours", "24", "--max-per-ticker", "6",
                                                  "--no-moves", "--all", "--dry-run"], a.data) if syms else None
    by = news_by_symbol(news)
    sides = {}
    for h in hits:
        sides.setdefault(h["symbol"], set()).update(h["setups"])
    rows = []
    for h in hits:
        s, side = h["symbol"], h["setups"][0]
        up = side == "orb_up"
        holding = h["price"] > h["range_high"] if up else h["price"] < h["range_low"]
        whip = len(sides[s]) > 1
        v = by.get(s, {"net": 0, "pos": 0, "neg": 0, "filings": [], "top": []})
        if v["net"] == 0:
            agree = "no company news"
        elif (v["net"] > 0) == up:
            agree = "agrees"
        else:
            agree = "conflicts"
        status = "whipsaw" if whip else ("holding" if holding else "back inside")
        rows.append((status != "holding", agree != "agrees", h["trigger_time"], s, side, h, status, agree, v))
    rows.sort(key=lambda r: r[:3])
    src = "Zerodha Kite" if token_ok(a.data) else "Yahoo"
    n_index = (scan.get("scanned") or {}).get("fetched") or 0
    lines = ["# Opening-range scan + news, %s IST (%s)" % (now.strftime("%a %d-%b-%Y %H:%M"), src), "",
             "%d of %d %s stocks triggered. Holding + news agrees comes first." % (len(syms), n_index, a.index), ""]
    if n_index and len(syms) >= 0.7 * n_index:
        lines += ["> Most of the index has triggered: on its own the signal is weak today.", ""]
    lines += ["| Stock | Side | Trigger | Range | Now | Status | News | Headline |",
              "|---|---|---|---|---|---|---|---|"]
    for _, _, _, s, side, h, status, agree, v in rows:
        top = v["top"][0] if v["top"] else None
        flag = " `!` filing" if v["filings"] else ""
        lines.append("| **%s** | %s | %s | %s–%s | %s | %s | %s %s%s | %s |" % (
            s, "▲ up" if side == "orb_up" else "▼ down", h["trigger_time"], h["range_low"], h["range_high"],
            h["price"], status, mood(v["net"]).split()[0], agree, flag,
            md_link(top["title"], top["link"]) if top else ""))
    path = write_report(a.data, "orb", now, lines + FOOT)
    best = [r[3] + (" ▲" if r[4] == "orb_up" else " ▼") for r in rows if r[6] == "holding" and r[7] == "agrees"]
    notify("ORB %s: %d hits" % (now.strftime("%H:%M"), len(syms)),
           ("Holding + news agrees: " + ", ".join(best[:5])) if best else "No hit has both a holding break and agreeing news.")
    print(path)
    return 0


def do_evening(a, now):
    news = run_json([NEWS, "--index", "NIFTY100", "--no-headlines", "--no-moves", "--all", "--dry-run",
                     "--hours", "24"], a.data)
    items = [i for i in (news or {}).get("items", []) if i["kind"] == "filing"]
    imp = [i for i in items if i["important"]]
    lines = ["# Evening filings, Nifty 100, %s IST" % now.strftime("%a %d-%b-%Y %H:%M"), "",
             "%d filings today, %d marked `!` (results, board outcomes, dividends, deals, ratings...)." % (
                 len(items), len(imp)), "", "| Time | Stock | Filing |", "|---|---|---|"]
    for i in imp + [i for i in items if not i["important"]][:40]:
        t = (i.get("time") or "")[11:16]
        lines.append("| %s | %s%s | %s |" % (t, "`!` " if i["important"] else "", i["symbol"], md_link(i["title"], i["link"])))
    path = write_report(a.data, "evening", now, lines + FOOT)
    notify("Evening filings", "%d important filings in the Nifty 100 today: %s" % (
        len(imp), ", ".join(dict.fromkeys(i["symbol"] for i in imp))[:150]))
    print(path)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Scheduled runs of the Indian trader skills")
    ap.add_argument("mode", choices=["reminder", "premarket", "orb", "evening"])
    ap.add_argument("--data", default=DEFAULT_DATA, help="folder holding trader/ (watchlist, state, reports)")
    ap.add_argument("--index", default="NIFTY50", help="orb: index to scan")
    ap.add_argument("--force", action="store_true", help="run on weekends too")
    a = ap.parse_args()
    now = _dt.datetime.now(IST).replace(microsecond=0)
    if now.weekday() >= 5 and not a.force:
        return 0
    return {"reminder": do_reminder, "premarket": do_premarket, "orb": do_orb, "evening": do_evening}[a.mode](a, now)


if __name__ == "__main__":
    sys.exit(main())

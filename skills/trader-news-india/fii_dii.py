#!/usr/bin/env python3
"""FII / DII money flows and derivatives positioning for the Indian market. Standard library only.

    python3 fii_dii.py                 # today's cash flows, NSDL FPI, F&O positioning (5 sessions)
    python3 fii_dii.py --days 10
    python3 fii_dii.py --json

Sources:
  cash      NSE provisional FII/FPI and DII buy / sell / net in the cash market
            (www.nseindia.com/api/fiidiiTradeReact; published after ~18:00 IST).
            Only the latest day is served, so each run adds it to
            trader/state/fii_dii.json and the history (5-day, 20-day sums) builds up.
  nsdl      NSDL confirmed FPI investment (equity, debt), reported a day later
            (www.fpi.nsdl.co.in/web/Reports/Latest.aspx).
  sectors   NSDL fortnightly sector-wise FPI report: assets held and net buying /
            selling per sector for the last two fortnights.
  deals     NSE bulk and block deals of the day (who bought / sold large blocks),
            buyers and sellers matched to FII (foreign funds, banks) or DII
            (mutual funds, insurers) by name.
  f&o       NSE participant-wise open interest (nsearchives .../fao_participant_oi_DDMMYYYY.csv):
            FII / DII / Pro / Client index futures long vs short, index options, per day.

Positioning is what the big players hold, not a forecast. Exit 0 = data, 1 = none.
"""

import argparse
import csv
import datetime as _dt
import html
import io
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
CASH = "https://www.nseindia.com/api/fiidiiTradeReact"
NSDL = "https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx"
PART_OI = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_%s.csv"
STATE = "trader/state/fii_dii.json"
NSDL_SEL = "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx"
NSDL_STATIC = "https://www.fpi.nsdl.co.in/web/"
DEALS = {"bulk": "https://nsearchives.nseindia.com/content/equities/bulk.csv",
         "block": "https://nsearchives.nseindia.com/content/equities/block.csv"}
# deal parties: names that mark a foreign (FII/FPI) or domestic institution (DII); everything else is "other"
DII_NAMES = re.compile(r"\b(mutual fund|\bmf\b|life insurance|insurance|\blic\b|pension|epfo|amc|"
                       r"asset management|nippon india|sbi funds|hdfc trustee|icici prudential|kotak mahindra trustee|"
                       r"axis mutual|aditya birla sun life|uti|mirae asset mutual|dsp|tata mutual|bandhan)\b", re.I)
FII_NAMES = re.compile(r"\b(fpi|pte\.? ?ltd|plc|llc|l\.p\.|s\.a\.|sicav|ucits|fund(?:s)? (?:ltd|limited|inc)|"
                       r"goldman|morgan stanley|citigroup|bnp paribas|societe generale|jp ?morgan|nomura|merrill|"
                       r"ubs|bofa|vanguard|blackrock|fidelity|government of singapore|abu dhabi|norges|"
                       r"copthall|mauritius|cayman|singapore|integrated core|ghisallo|goldman sachs)\b", re.I)
# proprietary / high-frequency traders: they buy and sell the same day, so their deals are not investment
PROP_NAMES = re.compile(r"\b(graviton|hrti|plutus wealth|monet securities|qe securities|junomoneta|silverleaf|"
                        r"nk securities|mathisys|alphagrep|tower research|jane street|optiver|citadel|irage|"
                        r"dolat|sixth sense|microcurves|f3 advisors|elixir wealth|ss corporate|share india)\b", re.I)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def num(x):
    x = str(x).strip().replace(",", "")
    neg = x.startswith("(") and x.endswith(")")
    x = x.strip("()")
    try:
        v = float(x)
    except ValueError:
        return None
    return -v if neg else v


def cash_flows(errors):
    try:
        rows = json.loads(get(CASH))
    except Exception as e:  # noqa: BLE001
        errors.append("NSE FII/DII cash: %s" % str(e)[:80])
        return None
    out = {}
    for r in rows:
        cat = "FII" if r.get("category", "").upper().startswith("FII") else "DII"
        out["date"] = _dt.datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat()
        out[cat] = {"buy": num(r["buyValue"]), "sell": num(r["sellValue"]), "net": num(r["netValue"])}
    return out if "FII" in out and "DII" in out else None


def nsdl_fpi(errors):
    try:
        t = get(NSDL).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        errors.append("NSDL FPI: %s" % str(e)[:80])
        return None
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    m = re.search(r"Daily Trends in FPI Investments on (\d{2}-\w{3}-\d{4})", t)
    eq = re.search(r"Equity Stock Exchange .*?Sub-total ([\d.,()-]+) ([\d.,()-]+) ([\d.,()-]+) ([\d.,()-]+)", t)
    debt = re.findall(r"Debt-[\w-]+ Stock Exchange .*?Sub-total [\d.,()-]+ [\d.,()-]+ ([\d.,()-]+)", t)
    if not (m and eq):
        errors.append("NSDL FPI: page layout not recognised")
        return None
    return {"date": _dt.datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat(),
            "equity_buy": num(eq.group(1)), "equity_sell": num(eq.group(2)), "equity_net": num(eq.group(3)),
            "equity_net_usd_m": num(eq.group(4)), "debt_net": sum(num(d) or 0 for d in debt)}


def _cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I)]


def nsdl_sectors(errors):
    """Latest NSDL fortnightly report: per sector equity AUC and net investment (INR crore) for 2 fortnights."""
    try:
        sel = get(NSDL_SEL).decode("utf-8", "replace")
        path = re.search(r'value="~/(StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/[^"]+)"', sel).group(1)
        t = get(NSDL_STATIC + path).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        errors.append("NSDL sector report: %s" % str(e)[:80])
        return None
    rows = [_cells(r) for r in re.findall(r"<tr.*?</tr>", t, flags=re.S | re.I)]
    head = next((r for r in rows if len(r) == 6 and "AUC" in r[2]), None)
    out = []
    for r in rows:
        # Sr, Sector, then 4 blocks (AUC, net, net, AUC) x 24 columns (12 INR then 12 USD); equity is column 0
        if len(r) >= 98 and r[0].isdigit():
            out.append({"sector": r[1], "auc": num(r[2 + 72]), "net1": num(r[2 + 24]), "net2": num(r[2 + 48])})
    if not out:
        errors.append("NSDL sector report: table layout not recognised")
        return None
    return {"periods": head[3:5] if head else ["first fortnight", "second fortnight"],
            "as_of": head[5] if head else "", "sectors": out}


def deals(errors):
    out = []
    for kind, url in DEALS.items():
        try:
            rows = list(csv.DictReader(io.StringIO(get(url).decode("utf-8", "replace"))))
        except Exception as e:  # noqa: BLE001
            errors.append("NSE %s deals: %s" % (kind, str(e)[:80]))
            continue
        for r in rows:
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("Symbol") or r.get("Date", "").upper().startswith("NO RECORD"):
                continue
            name = r.get("Client Name", "")
            who = ("prop" if PROP_NAMES.search(name) else "DII" if DII_NAMES.search(name)
                   else "FII" if FII_NAMES.search(name) else "other")
            qty, price = num(r.get("Quantity Traded")), num(r.get("Trade Price / Wght. Avg. Price"))
            out.append({"kind": kind, "date": r.get("Date"), "symbol": r["Symbol"], "client": name, "who": who,
                        "side": r.get("Buy/Sell", "").upper(), "qty": qty, "price": price,
                        "value_cr": (qty or 0) * (price or 0) / 1e7})
    return out


def participant_oi(day):
    data = get(PART_OI % day.strftime("%d%m%Y")).decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(data)))
    head = next((r for r in rows if r and r[0].strip() == "Client Type"), None)
    if not head:
        return None
    cols = [h.strip() for h in head]
    out = {}
    for r in rows:
        if r and r[0].strip() in ("FII", "DII", "Pro", "Client"):
            out[r[0].strip()] = {c: num(v) for c, v in zip(cols[1:], r[1:])}
    return out or None


def oi_history(n, today, errors):
    days, d, tries = [], today, 0
    while len(days) < n and tries < n * 2 + 6:
        tries += 1
        if d.weekday() < 5:
            try:
                oi = participant_oi(d)
            except Exception:  # noqa: BLE001 - holiday or not published yet
                oi = None
            if oi:
                days.append((d, oi))
            time.sleep(0.3)
        d -= _dt.timedelta(days=1)
    if not days:
        errors.append("NSE participant OI: no file in the last %d days" % tries)
    return days[::-1]


def summarise_oi(oi):
    f = oi["FII"]
    il, ish = f["Future Index Long"], f["Future Index Short"]
    c = oi["Client"]
    return {
        "fii_idx_fut_long": il, "fii_idx_fut_short": ish, "fii_idx_fut_net": il - ish,
        "fii_idx_long_pct": 100 * il / (il + ish) if il + ish else None,
        "fii_stk_fut_net": f["Future Stock Long"] - f["Future Stock Short"],
        "fii_call_net": f["Option Index Call Long"] - f["Option Index Call Short"],
        "fii_put_net": f["Option Index Put Long"] - f["Option Index Put Short"],
        "client_idx_long_pct": 100 * c["Future Index Long"] / (c["Future Index Long"] + c["Future Index Short"]),
    }


def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"cash": {}}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)
    except OSError:
        pass


def cr(x):
    return "{:+,.0f} cr".format(x) if x is not None else "n/a"


def main(argv=None):
    ap = argparse.ArgumentParser(description="FII / DII flows and F&O positioning (NSE, NSDL)")
    ap.add_argument("--days", type=int, default=5, help="sessions of participant OI to show (5)")
    ap.add_argument("--no-sectors", action="store_true", help="skip the NSDL sector report")
    ap.add_argument("--no-deals", action="store_true", help="skip bulk / block deals")
    ap.add_argument("--all-deals", action="store_true", help="also list deals by individuals and brokers")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = _dt.datetime.now(IST)
    errors = []
    st = load_state()
    cash = cash_flows(errors)
    if cash:
        st.setdefault("cash", {})[cash["date"]] = {"FII": cash["FII"]["net"], "DII": cash["DII"]["net"]}
        save_state(st)
    hist = sorted(st.get("cash", {}).items())
    fpi = nsdl_fpi(errors)
    ois = oi_history(max(2, a.days), now.date(), errors)
    oisum = [(d, summarise_oi(o)) for d, o in ois]
    secs = None if a.no_sectors else nsdl_sectors(errors)
    dls = [] if a.no_deals else deals(errors)

    if a.json:
        print(json.dumps({"as_of": now.isoformat(), "cash": cash, "cash_history": dict(hist), "nsdl_fpi": fpi,
                          "participant_oi": [{"date": d.isoformat(), **s} for d, s in oisum],
                          "nsdl_sectors": secs, "deals": dls, "errors": errors},
                         indent=2))
        return 0 if cash or fpi or oisum else 1

    L = ["FII / DII flows and positioning, %s." % now.strftime("%a %d-%b-%Y %H:%M IST")]
    if cash:
        f, d = cash["FII"], cash["DII"]
        L += ["", "Cash market, provisional (NSE), %s:" % _dt.date.fromisoformat(cash["date"]).strftime("%d-%b"),
              "  FII/FPI  buy %s  sell %s  net %s  %s" % ("{:,.0f}".format(f["buy"]), "{:,.0f}".format(f["sell"]),
                                                       cr(f["net"]), "BUYERS" if f["net"] > 0 else "SELLERS"),
              "  DII      buy %s  sell %s  net %s  %s" % ("{:,.0f}".format(d["buy"]), "{:,.0f}".format(d["sell"]),
                                                       cr(d["net"]), "BUYERS" if d["net"] > 0 else "SELLERS"),
              "  combined net %s" % cr(f["net"] + d["net"])]
        if len(hist) > 1:
            last = hist[-20:]
            f5 = sum(v["FII"] for _, v in hist[-5:])
            d5 = sum(v["DII"] for _, v in hist[-5:])
            L.append("  history kept here (%d days): last %d FII %s, DII %s%s" % (
                len(hist), min(5, len(hist)), cr(f5), cr(d5),
                "; last %d FII %s, DII %s" % (len(last), cr(sum(v["FII"] for _, v in last)),
                                              cr(sum(v["DII"] for _, v in last))) if len(hist) > 5 else ""))
            L.append("  " + "  ".join("%s F%s/D%s" % (_dt.date.fromisoformat(k).strftime("%d-%b"),
                                                       "{:+,.0f}".format(v["FII"]), "{:+,.0f}".format(v["DII"]))
                                       for k, v in hist[-5:]))
        else:
            L.append("  (history starts today: NSE serves only the latest day; run this daily after 18:00 to build it)")
    if fpi:
        L += ["", "FPI confirmed (NSDL, reported %s): equity net %s (US$ %s m), debt net %s" % (
            _dt.date.fromisoformat(fpi["date"]).strftime("%d-%b"), cr(fpi["equity_net"]),
            "{:+,.0f}".format(fpi["equity_net_usd_m"] or 0), cr(fpi["debt_net"]))]
    if oisum:
        L += ["", "F&O positioning (NSE participant-wise open interest, contracts):",
              "  date     FII idx fut long  short    net     long%  | FII idx calls net  puts net | clients long%"]
        for d, s in oisum:
            L.append("  %s  %9s %9s %+9s  %5.1f%%  | %+12s %+10s | %5.1f%%" % (
                d.strftime("%d-%b"), "{:,.0f}".format(s["fii_idx_fut_long"]), "{:,.0f}".format(s["fii_idx_fut_short"]),
                "{:,.0f}".format(s["fii_idx_fut_net"]), s["fii_idx_long_pct"], "{:,.0f}".format(s["fii_call_net"]),
                "{:,.0f}".format(s["fii_put_net"]), s["client_idx_long_pct"]))
        last = oisum[-1][1]
        p = last["fii_idx_long_pct"]
        tone = ("heavily short (below 30%)" if p < 30 else "net short" if p < 45 else "balanced" if p <= 55
                else "net long" if p <= 70 else "heavily long (above 70%)")
        L.append("  FII index futures: %.1f%% long = %s." % (p, tone))
        if len(oisum) > 1:
            dlt = last["fii_idx_fut_net"] - oisum[-2][1]["fii_idx_fut_net"]
            L.append("  Change vs previous session: FII net index futures %s contracts (%s)." % (
                "{:+,.0f}".format(dlt), "added longs / covered shorts" if dlt > 0 else "added shorts / cut longs"))
        L.append("  Clients (retail) usually sit on the other side of FIIs in index futures.")
    if secs:
        ss = secs["sectors"]
        for x in ss:
            x["net"] = (x["net1"] or 0) + (x["net2"] or 0)
        L += ["", "FPI money by sector (NSDL fortnightly, equity, INR crore; %s | %s; held %s):" % (
            secs["periods"][0].replace("Net Investment ", ""), secs["periods"][1].replace("Net Investment ", ""),
            secs["as_of"].replace("AUC as on ", ""))]
        fmt_x = lambda x: "  %-42s %+9s %+9s  month %+9s  held %10s" % (
            x["sector"][:42], "{:,.0f}".format(x["net1"] or 0), "{:,.0f}".format(x["net2"] or 0),
            "{:,.0f}".format(x["net"]), "{:,.0f}".format(x["auc"] or 0))
        buys = sorted([x for x in ss if x["net"] > 0], key=lambda x: -x["net"])[:6]
        sells = sorted([x for x in ss if x["net"] < 0], key=lambda x: x["net"])[:6]
        L += ["  bought most:"] + [fmt_x(x) for x in buys] + ["  sold most:"] + [fmt_x(x) for x in sells]
        tot = sum(x["net"] for x in ss)
        L.append("  all sectors: %s over the month" % cr(tot))
    if not a.no_deals:
        inst = [d for d in dls if a.all_deals or d["who"] in ("FII", "DII")]
        L += ["", "Bulk / block deals today by institutions (NSE; FII / DII matched by name)%s:" % (
            "" if not a.all_deals else ", all parties")]
        if inst:
            for d in sorted(inst, key=lambda d: -d["value_cr"]):
                L.append("  %-5s %-4s %-11s %-4s %12s sh @ %10s  = %8s cr  %s" % (
                    d["kind"], d["who"], d["symbol"], d["side"], "{:,.0f}".format(d["qty"] or 0),
                    "{:,.2f}".format(d["price"] or 0), "{:,.1f}".format(d["value_cr"]), d["client"][:48]))
        else:
            L.append("  none today (%d deals by individuals, brokers and same-day prop traders; --all-deals lists them)"
                     % len(dls))
        agg = {}
        for d in dls:
            if d["who"] not in ("FII", "DII"):
                continue
            k = (d["symbol"], d["who"])
            agg[k] = agg.get(k, 0) + (d["value_cr"] if d["side"] == "BUY" else -d["value_cr"])
        if agg:
            L.append("  net by stock: " + "; ".join("%s %s %s cr" % (s_, w, "{:+,.1f}".format(v))
                                                     for (s_, w), v in sorted(agg.items(), key=lambda kv: -abs(kv[1]))[:12]))
    for e in errors:
        L.append("note: could not read " + e)
    L.append("note: NSE cash figures are provisional (published ~18:00 IST); NSDL confirms them a day later.")
    L.append("Flows and positioning, not forecasts: FIIs can be wrong and positions change daily.")
    print("\n".join(L))
    return 0 if cash or fpi or oisum or secs or dls else 1


if __name__ == "__main__":
    sys.exit(main())

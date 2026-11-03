#!/usr/bin/env python3
"""BOS / CHoCH scanner for Indian stocks (NSE). Standard library only.

A Python port of the market-structure part of the user's Pine script
"Gold Navigator + Regime (BOS/CHoCH)", run over a whole index:

    python3 bos_india.py                                  # Nifty 50 + Next 50, 15-minute bars
    python3 bos_india.py --index NIFTY50 --tf 5
    python3 bos_india.py --symbols RELIANCE,TCS --tf 60 --recent 10
    python3 bos_india.py --tf D --swing 5                 # daily structure

Same rules as the Pine script (defaults match its inputs):
  pivots      ta.pivothigh/low(high/low, --swing, --swing)
  break       a bull candle CLOSES above the last unbroken swing high (or the
              protected high after a bearish structure) by --min-break x ATR14,
              body >= --min-body x ATR14, ADX14 >= --adx-min, and at least
              --cooldown bars since the last mark
  confirm     the next --confirm candles must not close back below the level
  BOS/CHoCH   CHoCH when the break is against the current structure, else BOS
  BUY signal  on a confirmed bullish break: entry = close of the confirming
              candle, SL = low of the breakout candle (- --sl-buffer),
              TP = entry + --tp-r x risk (or --tp-pct %); one signal at a time
              until SL or TP (SL first when both hit in one candle)
  SELL signal mirror image

Not ported: the Regime zone filter ("block signals while a sideways zone is
active"). Every signal here is unfiltered by regime; the output says so.

Data: Zerodha Kite when today's token exists (see trader-scanner-india),
otherwise Yahoo. Only completed candles are used (the forming one is
dropped), so a mark never repaints.

A scan is a list of charts that match a rule, not a list of stocks to buy.
Exit code 0 when something matched, 1 when not, 2 on bad input.
"""

import argparse
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "trader-scanner-india"))
import scan_india as S  # noqa: E402  (index lists, Yahoo, Kite source picking)

TF = {  # --tf -> (Kite interval, Yahoo interval, Yahoo range, minutes per bar, calendar days to fetch)
    "5": ("5minute", "5m", "30d", 5, 20),
    "15": ("15minute", "15m", "60d", 15, 45),
    "30": ("30minute", "30m", "60d", 30, 60),
    "60": ("60minute", "60m", "180d", 60, 150),
    "D": ("day", "1d", "2y", 375, 700),
}


# ---------------------------------------------------------------- indicators

def rma(xs, n):
    out, prev = [None] * len(xs), None
    for i, x in enumerate(xs):
        if i < n - 1:
            continue
        prev = sum(xs[i - n + 1:i + 1]) / n if prev is None else prev + (x - prev) / n
        out[i] = prev
    return out


def atr_dmi(h, l, c, n=14):
    """Wilder ATR and ADX (Pine ta.atr / ta.dmi)."""
    tr, pdm, mdm = [], [], []
    for i in range(len(c)):
        if i == 0:
            tr.append(h[0] - l[0]); pdm.append(0.0); mdm.append(0.0)
            continue
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    atr, sp, sm = rma(tr, n), rma(pdm, n), rma(mdm, n)
    dx = []
    for a, p, m in zip(atr, sp, sm):
        if a is None or not a:
            dx.append(0.0)
            continue
        pi, mi = 100 * p / a, 100 * m / a
        dx.append(100 * abs(pi - mi) / (pi + mi) if pi + mi else 0.0)
    adx = rma(dx, n)
    return atr, adx


def pivots(xs, k, high):
    """Pine ta.pivothigh/low: value at i-k, known at bar i. Returns {i: value}."""
    out = {}
    for i in range(2 * k, len(xs)):
        c = i - k
        left, right = xs[c - k:c], xs[c + 1:i + 1]
        if high and xs[c] > max(left) and xs[c] >= max(right):
            out[i] = xs[c]
        if not high and xs[c] < min(left) and xs[c] <= min(right):
            out[i] = xs[c]
    return out


# ---------------------------------------------------------------- the engine

def structure(s, p):
    """Replay the Pine BOS/CHoCH state machine. Returns (marks, signals, trend)."""
    o, h, l, c, t = s["o"], s["h"], s["l"], s["c"], s["t"]
    n = len(c)
    atr, adx = atr_dmi(h, l, c)
    ph, pl = pivots(h, p.swing, True), pivots(l, p.swing, False)

    st = dict(swH=None, swHBar=None, swHBroken=True, swL=None, swLBar=None, swLBroken=True,
              trend=0, protH=None, protHBar=None, protL=None, protLBar=None, lastMark=None,
              pend=0, pendLvl=None, pendFrom=None, pendBar=None, pendSwing=False, pendHi=None, pendLo=None)
    marks, signals, trade = [], [], None

    for i in range(n):
        if i in ph:
            st.update(swH=ph[i], swHBar=i - p.swing, swHBroken=False)
        if i in pl:
            st.update(swL=pl[i], swLBar=i - p.swing, swLBroken=False)
        a = atr[i]
        if a is None:
            continue
        trending = not p.adx_min or (adx[i] or 0) >= p.adx_min
        strong = abs(c[i] - o[i]) >= p.min_body * a
        pad = p.min_break * a
        cool = st["lastMark"] is None or i - st["lastMark"] >= p.cooldown
        ok = trending and strong and cool and st["pend"] == 0

        up_prot = p.protected and st["trend"] == -1 and st["protH"] is not None
        dn_prot = p.protected and st["trend"] == 1 and st["protL"] is not None
        up_lvl, up_bar = (st["protH"], st["protHBar"]) if up_prot else (st["swH"], st["swHBar"])
        dn_lvl, dn_bar = (st["protL"], st["protLBar"]) if dn_prot else (st["swL"], st["swLBar"])
        up_ok = up_prot or (not st["swHBroken"] and st["swH"] is not None)
        dn_ok = dn_prot or (not st["swLBroken"] and st["swL"] is not None)
        x_up = c[i] if p.confirm_by == "close" else h[i]
        x_dn = c[i] if p.confirm_by == "close" else l[i]

        if ok and up_ok and c[i] > o[i] and x_up > up_lvl + pad:
            st.update(pend=1, pendLvl=up_lvl, pendFrom=up_bar, pendBar=i, pendSwing=not up_prot, pendHi=h[i], pendLo=l[i])
            if not up_prot:
                st["swHBroken"] = True
        elif ok and dn_ok and c[i] < o[i] and x_dn < dn_lvl - pad:
            st.update(pend=-1, pendLvl=dn_lvl, pendFrom=dn_bar, pendBar=i, pendSwing=not dn_prot, pendHi=h[i], pendLo=l[i])
            if not dn_prot:
                st["swLBroken"] = True

        sig = None
        if st["pend"]:
            d = st["pend"]
            failed = i > st["pendBar"] and (c[i] < st["pendLvl"] if d == 1 else c[i] > st["pendLvl"])
            if failed:
                if st["pendSwing"] and d == 1 and st["pendLvl"] == st["swH"]:
                    st["swHBroken"] = False
                if st["pendSwing"] and d == -1 and st["pendLvl"] == st["swL"]:
                    st["swLBroken"] = False
                st["pend"] = 0
            elif i - st["pendBar"] >= p.confirm:
                choch = st["trend"] == (-1 if d == 1 else 1)
                marks.append({"dir": d, "kind": "CHoCH" if choch else "BOS", "level": st["pendLvl"],
                              "break_bar": st["pendBar"], "confirm_bar": i})
                if d == 1:
                    st.update(trend=1, protL=st["swL"], protLBar=st["swLBar"], protH=None, swHBroken=True)
                else:
                    st.update(trend=-1, protH=st["swH"], protHBar=st["swHBar"], protL=None, swLBroken=True)
                st["lastMark"] = i
                stop = st["pendLo"] - p.sl_buffer if d == 1 else st["pendHi"] + p.sl_buffer
                sig = (d, choch, stop)
                st["pend"] = 0

        # open trade: SL / TP
        if trade and i > trade["bar"] and trade["status"] == "open":
            d = trade["dir"]
            hit_sl = l[i] <= trade["sl"] if d == 1 else h[i] >= trade["sl"]
            hit_tp = h[i] >= trade["tp"] if d == 1 else l[i] <= trade["tp"]
            if hit_sl or hit_tp:
                trade.update(status="SL hit" if hit_sl else "TP hit", exit_bar=i)
        flat = not p.one_at_a_time or not trade or trade["status"] != "open"
        if sig and flat:
            d, choch, stop = sig
            want = (d == 1 and p.longs) or (d == -1 and p.shorts)
            want = want and (p.on_choch if choch else p.on_bos)
            entry = c[i]
            risk = entry - stop if d == 1 else stop - entry
            if want and risk > 0 and (not p.max_risk_pct or risk / entry * 100 <= p.max_risk_pct):
                move = entry * p.tp_pct / 100 if p.tp_pct else p.tp_r * risk
                trade = {"dir": d, "kind": "CHoCH" if choch else "BOS", "bar": i, "entry": entry, "sl": stop,
                         "tp": entry + move if d == 1 else entry - move, "risk": risk, "status": "open"}
                signals.append(trade)
    return marks, signals, st["trend"]


# ---------------------------------------------------------------- data

def completed(s, minutes, now):
    """Drop the candle that is still forming (and empty rows)."""
    keep = [k for k in range(len(s["t"])) if None not in (s["o"][k], s["h"][k], s["l"][k], s["c"][k])]
    if minutes < 375:
        keep = [k for k in keep if S.ist(s["t"][k]) + _dt.timedelta(minutes=minutes) <= now]
    else:
        keep = [k for k in keep if S.ist(s["t"][k]).date() < now.date() or now.time() >= S.CLOSE]
    return {key: [s[key][k] for k in keep] for key in ("t", "o", "h", "l", "c", "v")}


def fetch(a, now, symbols, progress):
    kite_iv, y_iv, y_rng, minutes, days = TF[a.tf]
    source, kite = a.source_pick
    if source == "kite":
        data, failed = S.kite_fetch(kite, symbols, kite_iv, now - _dt.timedelta(days=days), now, progress)
    else:
        data, failed = {}, []
        progress("Yahoo %s candles for %d stocks (~%d s)..." % (y_iv, len(symbols), len(symbols) // 2))
        for k, sym in enumerate(symbols):
            try:
                ser = S.fetch_chart(sym, y_rng, y_iv)
                (data.__setitem__(sym, ser) if ser and ser["t"] else failed.append(sym))
            except S.ScanError:
                failed.append(sym)
            if (k + 1) % 25 == 0 or k + 1 == len(symbols):
                progress("  %d of %d charts" % (k + 1, len(symbols)))
    return source, {k: completed(v, minutes, now) for k, v in data.items()}, failed


# ---------------------------------------------------------------- report

def stamp(s, i, tf):
    d = S.ist(s["t"][i])
    return d.strftime("%d-%b") if tf == "D" else d.strftime("%d-%b %H:%M")


def scan(a, now, symbols, progress):
    source, data, failed = fetch(a, now, symbols, progress)
    rows, thin = [], []
    for sym in symbols:
        s = data.get(sym)
        if not s or len(s["c"]) < 2 * a.swing + 20:
            if sym not in failed:
                thin.append(sym)
            continue
        marks, signals, trend = structure(s, a)
        last = len(s["c"]) - 1
        price = s["c"][-1]
        recent = [m for m in marks if last - m["confirm_bar"] < a.recent]
        sig = signals[-1] if signals else None
        if sig and (last - sig["bar"] >= a.recent and sig["status"] != "open"):
            sig = None
        rows.append({"symbol": sym, "price": price, "trend": trend, "marks": recent, "signal": sig,
                     "new": bool(sig) and last - sig["bar"] < a.recent,
                     "turnover_cr": sum(s["c"][k] * (s["v"][k] or 0) for k in range(max(0, last - 24), last + 1)) / S.CRORE,
                     "series": s, "last": last})
    return source, rows, failed, thin


def fmt(x):
    return S.money(x).replace("Rs ", "Rs ")


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE BOS / CHoCH scanner (port of the Gold Navigator Pine logic)")
    ap.add_argument("--index", nargs="+", default=["NIFTY50", "NIFTYNEXT50"], metavar="NAME")
    ap.add_argument("--symbols")
    ap.add_argument("--watchlist")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--tf", default="15", choices=list(TF), help="candle timeframe (default 15 minutes)")
    ap.add_argument("--recent", type=int, default=None, help="report marks/signals from the last N candles (default 25, 2 with --early)")
    ap.add_argument("--early", action="store_true", help="flag the BOS on the breakout candle itself (no follow-through wait; = --confirm 0 --recent 2)")
    g = ap.add_argument_group("structure (Pine defaults)")
    g.add_argument("--swing", type=int, default=12, help="pivot bars each side (12)")
    g.add_argument("--confirm-by", choices=["close", "wick"], default="close")
    g.add_argument("--adx-min", type=float, default=25.0, help="0 turns the ADX filter off (25)")
    g.add_argument("--min-body", type=float, default=0.8, help="break candle body x ATR (0.8)")
    g.add_argument("--min-break", type=float, default=0.1, help="close past the level x ATR (0.1)")
    g.add_argument("--no-protected", dest="protected", action="store_false", help="CHoCH on any swing, not only the protected one")
    g.add_argument("--confirm", type=int, default=2, help="follow-through candles (2)")
    g.add_argument("--cooldown", type=int, default=10, help="min bars between marks (10)")
    g = ap.add_argument_group("signals")
    g.add_argument("--no-sell", dest="shorts", action="store_false")
    g.add_argument("--no-buy", dest="longs", action="store_false")
    g.add_argument("--no-bos-signal", dest="on_bos", action="store_false")
    g.add_argument("--no-choch-signal", dest="on_choch", action="store_false")
    g.add_argument("--tp-r", type=float, default=2.0, help="target = entry + N x risk (default 2)")
    g.add_argument("--tp-pct", type=float, default=0.0, help="target as %% of entry instead of R")
    g.add_argument("--sl-buffer", type=float, default=0.0, help="rupees beyond the breakout candle")
    g.add_argument("--max-risk-pct", type=float, default=0.0, help="skip if the stop is more than N %% away (0 = off)")
    g.add_argument("--many", dest="one_at_a_time", action="store_false", help="allow a new signal while one is open")
    ap.add_argument("--min-price", type=float, default=20.0)
    ap.add_argument("--source", choices=["auto", "kite", "yahoo"], default="auto")
    ap.add_argument("--kite-config", default=os.path.expanduser("~/.config/trader-india/kite.json"))
    ap.add_argument("--now")
    ap.add_argument("--state", default="trader/state/scanner_india.json")
    ap.add_argument("--out", default="trader/watchlist.json")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.early:
        a.confirm = 0
    if a.recent is None:
        a.recent = 2 if a.early else 25

    progress = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    now = S.parse_now(a.now)
    state = S.load_json(a.state, {}) or {}
    notes = []
    try:
        symbols = S.read_universe(a, state, now, notes)
        source, kite, note = S.pick_source(a, now)
        a.source_pick = (source, kite)
        if note:
            notes.append(note)
        source, rows, failed, thin = scan(a, now, symbols, progress)
    except S.ScanError as e:
        print(str(e))
        return 2 if "unknown index" in str(e) or "no symbols" in str(e) else 1
    S.write_json(a.state, state)
    rows = [r for r in rows if r["price"] >= a.min_price]
    tfname = "daily" if a.tf == "D" else a.tf + "-minute"

    buys = [r for r in rows if r["new"] and r["signal"]["dir"] == 1]
    sells = [r for r in rows if r["new"] and r["signal"]["dir"] == -1]
    older = [r for r in rows if r["signal"] and not r["new"]]  # still open, from before the window
    bull = [r for r in rows if any(m["dir"] == 1 for m in r["marks"])]
    bear = [r for r in rows if any(m["dir"] == -1 for m in r["marks"])]
    order = lambda rs: sorted(rs, key=lambda r: -r["turnover_cr"])

    def sig_line(r):
        g, s = r["signal"], r["series"]
        status = g["status"] + ("" if g["status"] == "open" else " " + stamp(s, g["exit_bar"], a.tf))
        return "  %-11s %s %-5s %s  @ %s  SL %s  TP %s  risk %.2f%%  now %s  [%s]" % (
            r["symbol"], "BUY " if g["dir"] == 1 else "SELL", g["kind"], stamp(s, g["bar"], a.tf),
            fmt(g["entry"]), fmt(g["sl"]), fmt(g["tp"]), g["risk"] / g["entry"] * 100, fmt(r["price"]), status)

    def mark_line(r, d):
        m = [x for x in r["marks"] if x["dir"] == d][-1]
        s = r["series"]
        return "  %-11s %-5s level %s  broke %s, confirmed %s  now %s" % (
            r["symbol"], m["kind"], fmt(m["level"]), stamp(s, m["break_bar"], a.tf),
            stamp(s, m["confirm_bar"], a.tf), fmt(r["price"]))

    lines = ["BOS / CHoCH scan (%s), %s candles, %s, last %d candles, completed candles only%s." % (
                 "Zerodha Kite" if source == "kite" else "Yahoo", tfname, now.strftime("%a %d-%b-%Y %H:%M IST"), a.recent,
                 ", EARLY: on the breakout candle, no follow-through check (more false breaks)" if a.confirm == 0 else ""),
             "%d requested, %d scanned, %d failed, %d too little data; %d new BUY and %d new SELL signals (%d older still open), %d bullish and %d bearish marks." % (
                 len(symbols), len(rows), len(failed), len(thin), len(buys), len(sells), len(older), len(bull), len(bear))]
    for title, rs, fn in (("BUY signals, last %d candles" % a.recent, buys, sig_line),
                          ("SELL signals, last %d candles" % a.recent, sells, sig_line),
                          ("Older signals still open", older, sig_line)):
        if rs:
            lines += ["", "%s (%d)" % (title, len(rs))] + [fn(r) for r in order(rs)]
    for title, rs, d in (("Bullish BOS / CHoCH", bull, 1), ("Bearish BOS / CHoCH", bear, -1)):
        if rs:
            lines += ["", "%s (%d)" % (title, len(rs))] + [mark_line(r, d) for r in order(rs)]
    up = sum(r["trend"] == 1 for r in rows)
    dn = sum(r["trend"] == -1 for r in rows)
    lines += ["", "Structure now: %d bullish, %d bearish, %d not set." % (up, dn, len(rows) - up - dn)]
    notes.append("Regime-zone filter of the Pine script is not applied: signals are unfiltered by sideways/choppy zones.")

    hits = []
    for r in rows:
        tags = ["%s_%s" % (m["kind"].lower(), "up" if m["dir"] == 1 else "down") for m in r["marks"]]
        if r["signal"]:
            tags.append("buy_signal" if r["signal"]["dir"] == 1 else "sell_signal")
        if tags:
            g = r["signal"]
            hits.append({"symbol": r["symbol"], "setups": sorted(set(tags)), "price": round(r["price"], 2),
                         "signal": None if not g else {k: (round(v, 2) if isinstance(v, float) else v)
                                                        for k, v in g.items() if k not in ("bar", "exit_bar")}})
    doc = {"mode": "bos", "timeframe": a.tf, "as_of": now.isoformat(), "market": "NSE", "universe": " ".join(a.index),
           "scanned": len(rows), "failed": failed, "hits": hits, "note": S.NOTE}
    if not a.no_write:
        S.write_json(a.out, doc)
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("\n".join(lines))
        for n in notes:
            print("note: " + n)
        if failed:
            print("failed: " + " ".join(failed[:20]))
        if not a.no_write:
            print("Wrote %d hits to %s." % (len(hits), a.out))
        print(S.NOTE)
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())

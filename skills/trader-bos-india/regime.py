"""Regime engine: sideways / choppy / consolidation zones and their breakouts.

A Python port of f_regime() in the user's Pine script "Gold Navigator +
Regime (BOS/CHoCH)" (defaults match its inputs). Run on the scan's own
candles (the Pine default regime timeframe is 15 minutes, the same as the
scan default).

regime(s) returns a dict of per-bar lists and the breakout events:
    active[i], top[i], bot[i], kind[i] (1 sideways, 2 choppy, 3 consolidation),
    trend_up[i], breaks = [{"bar", "dir", "top", "bot", "kind", "start_bar"}]
Values at bar i are known at the close of bar i.
"""

import math

NAMES = {1: "SIDEWAYS", 2: "CHOPPY", 3: "CONSOLIDATION"}

P = dict(rngLen=12, rngAtr=3.5, minCross=3, maxDrift=0.40, rgConfirm=2, baseLen=100,
         brkBuf=0.10, maxZoneAtr=4.5, backTol=0.25, maxBack=150,
         fastLen=10, erLow=0.20, erHigh=0.50, r2High=0.60, adxLen=10,
         volLen=20, compTh=55, chopTh=55, ciLow=38.2, ciHigh=61.8, maxX=4,
         bbMult=2.0, kcMult=1.5, atrFast=5, atrSlow=50, pctLen=120, rngTight=3.0, rngWide=7.0)


def _rma(xs, n):
    out, prev = [None] * len(xs), None
    for i in range(len(xs)):
        if i < n - 1:
            continue
        prev = sum(xs[i - n + 1:i + 1]) / n if prev is None else prev + (xs[i] - prev) / n
        out[i] = prev
    return out


def _ema(xs, n):
    out, prev, k = [None] * len(xs), None, 2 / (n + 1)
    for i in range(len(xs)):
        if i < n - 1:
            continue
        prev = sum(xs[i - n + 1:i + 1]) / n if prev is None else prev + k * (xs[i] - prev)
        out[i] = prev
    return out


def _linreg(ys, off):
    n = len(ys)
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in range(n))
    slope = sum((x - mx) * (y - my) for x, y in enumerate(ys)) / sxx
    return my + slope * (n - 1 - off - mx)


def _clamp(x):
    return max(0.0, min(1.0, x))


def _low_good(x, lo, hi):
    return _clamp((hi - x) / (hi - lo))


def _high_good(x, lo, hi):
    return _clamp((x - lo) / (hi - lo))


def regime(s, p=P):
    o, h, l, c = s["o"], s["h"], s["l"], s["c"]
    n = len(c)
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    pdm, mdm = [0.0], [0.0]
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    atr_a, sp, sm = _rma(tr, p["adxLen"]), _rma(pdm, p["adxLen"]), _rma(mdm, p["adxLen"])
    atrF, atrS, kcAtr = _rma(tr, p["atrFast"]), _rma(tr, p["atrSlow"]), _rma(tr, p["volLen"])
    fastMa, kcMid = _ema(c, p["fastLen"]), _ema(c, p["volLen"])
    L, F, V = p["rngLen"], p["fastLen"], p["volLen"]

    out = dict(active=[False] * n, top=[None] * n, bot=[None] * n, kind=[0] * n, trend_up=[True] * n, breaks=[])
    bbw, body, cross = [None] * n, [None] * n, [0] * n
    okCnt, lastBreak = 0, -100000
    zActive, zTop, zBot, zAtr, zType, zStart, tCand, tCandCnt = False, None, None, None, 1, None, 1, 0
    start = max(p["atrSlow"], V, L, F) + 1

    for i in range(n):
        body[i] = abs(c[i] - o[i]) / (h[i] - l[i]) if h[i] > l[i] else 0.0
        if i >= V - 1:
            w = c[i - V + 1:i + 1]
            basis = sum(w) / V
            dev = math.sqrt(sum((x - basis) ** 2 for x in w) / V)
            bbw[i] = 2 * p["bbMult"] * dev / basis if basis else 0.0
        if i > 0 and fastMa[i] is not None and fastMa[i - 1] is not None:
            cross[i] = int((c[i] > fastMa[i] and c[i - 1] <= fastMa[i - 1]) or (c[i] < fastMa[i] and c[i - 1] >= fastMa[i - 1]))
        if sp[i] is not None and sm[i] is not None:
            out["trend_up"][i] = sp[i] >= sm[i]
        if i < start:
            continue

        win = sorted(tr[max(0, i - p["baseLen"] + 1):i + 1])
        baseAtr = win[max(0, math.ceil(0.5 * len(win)) - 1)] if len(win) >= p["baseLen"] else tr[i]
        rHH, rLL = max(h[i - L + 1:i + 1]), min(l[i - L + 1:i + 1])
        rH, rMid = rHH - rLL, (rHH + rLL) / 2
        rHeightAtr = rH / baseAtr if baseAtr > 0 else 99.0
        mCross = sum(1 for k in range(L - 1) if (c[i - k] - rMid) * (c[i - k - 1] - rMid) < 0)
        ys = c[i - L + 1:i + 1]
        lrNow = _linreg(ys, 0)
        lrOld = _linreg(ys, L - 1)
        rDrift = abs(lrNow - lrOld) / rH if rH > 0 else 0.0

        path = sum(abs(c[k] - c[k - 1]) for k in range(i - F + 1, i + 1))
        er = abs(c[i] - c[i - F]) / path if path > 0 else 0.0
        xs, yv = list(range(F)), c[i - F + 1:i + 1]
        mx, my = (F - 1) / 2, sum(yv) / F
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, yv))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in yv)
        r2 = (sxy * sxy / (sxx * syy)) if syy > 0 else 0.0
        trendStrong = er >= p["erHigh"] or (r2 >= p["r2High"] and er >= (p["erLow"] + p["erHigh"]) / 2)
        rangeOk = rHeightAtr <= p["rngAtr"] and mCross >= p["minCross"] and rDrift <= p["maxDrift"] and not trendStrong

        fHH, fLL = max(h[i - F + 1:i + 1]), min(l[i - F + 1:i + 1])
        ci = 100 * math.log10(sum(tr[i - F + 1:i + 1]) / (fHH - fLL)) / math.log10(F) if fHH > fLL else 50.0
        crossSum = sum(cross[i - F + 1:i + 1])
        w = c[i - V + 1:i + 1]
        basis = sum(w) / V
        dev = math.sqrt(sum((x - basis) ** 2 for x in w) / V)
        squeeze = (basis + p["bbMult"] * dev < kcMid[i] + p["kcMult"] * kcAtr[i]
                   and basis - p["bbMult"] * dev > kcMid[i] - p["kcMult"] * kcAtr[i])
        prev = [b for b in bbw[max(0, i - p["pctLen"]):i] if b is not None]
        bbwPct = 100 * sum(1 for b in prev if b <= bbw[i]) / len(prev) if len(prev) >= p["pctLen"] else 50.0
        atrRatio = atrF[i] / atrS[i] if atrS[i] else 1.0
        rangeAtr = (max(h[i - V + 1:i + 1]) - min(l[i - V + 1:i + 1])) / atrS[i] if atrS[i] else p["rngWide"]
        avgBody = sum(body[i - F + 1:i + 1]) / F

        comp = 100 * (0.30 * (1.0 if squeeze else 0.0) + 0.25 * _low_good(bbwPct, 20, 70)
                      + 0.20 * _low_good(atrRatio, 0.75, 1.10) + 0.25 * _low_good(rangeAtr, p["rngTight"], p["rngWide"]))
        whip = 100 * (0.30 * _high_good(ci, p["ciLow"], p["ciHigh"]) + 0.30 * _clamp(crossSum / p["maxX"])
                      + 0.20 * _low_good(er, p["erLow"], p["erHigh"]) + 0.20 * _low_good(avgBody, 0.30, 0.60))
        cls = 3 if comp >= p["compTh"] and comp >= whip else 2 if whip >= p["chopTh"] else 1

        okCnt = okCnt + 1 if rangeOk else 0
        if zActive:
            up = c[i] > zTop + p["brkBuf"] * zAtr or (trendStrong and c[i] > c[i - F] and c[i] > zTop)
            dn = c[i] < zBot - p["brkBuf"] * zAtr or (trendStrong and c[i] < c[i - F] and c[i] < zBot)
            if up or dn:
                out["breaks"].append({"bar": i, "dir": 1 if up else -1, "top": zTop, "bot": zBot,
                                      "kind": zType, "start_bar": zStart})
                zActive, okCnt, lastBreak = False, 0, i
        if zActive:
            nt, nb = max(zTop, h[i]), min(zBot, l[i])
            if nt - nb <= p["maxZoneAtr"] * zAtr:
                zTop, zBot = nt, nb
            if cls == zType:
                tCandCnt = 0
            else:
                if cls == tCand:
                    tCandCnt += 1
                else:
                    tCand, tCandCnt = cls, 1
                if tCandCnt >= p["rgConfirm"]:
                    zType, tCandCnt = cls, 0
        if not zActive and i - lastBreak >= max(2, L // 2) and okCnt >= p["rgConfirm"]:
            zActive, zTop, zBot, zAtr, zType, tCandCnt = True, rHH, rLL, baseAtr, cls, 0
            tol, back = p["backTol"] * zAtr, L - 1
            for k in range(L, p["maxBack"] + 1):
                if k > i or k > i - lastBreak - 1:
                    break
                if h[i - k] > zTop + tol or l[i - k] < zBot - tol:
                    break
                back = k
            zStart = i - back
        out["active"][i], out["top"][i], out["bot"][i], out["kind"][i] = zActive, zTop, zBot, zType
    return out

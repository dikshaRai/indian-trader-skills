"""Zerodha Kite Connect data for scan_india.py. Standard library only. Read-only:
this module calls only the instruments and historical-candle endpoints and never
places, modifies or cancels orders.

Credentials live in a private file outside any project (default
~/.config/trader-india/kite.json, mode 600):

    {"api_key": "...", "api_secret": "...", "access_token": "...", "token_date": "2026-10-30"}

kite_login.py fills access_token and token_date each morning (Zerodha expires
tokens daily around 6 AM IST). Never paste these values into a chat.
"""

import csv
import datetime as _dt
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.kite.trade"
DEFAULT_CONFIG = os.path.expanduser("~/.config/trader-india/kite.json")
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
MIN_GAP = 0.35  # historical API allows 3 requests a second


class KiteError(Exception):
    pass


def load_config(path=DEFAULT_CONFIG):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        raise KiteError("no Kite config at %s: run kite_login.py --init" % path)
    except ValueError:
        raise KiteError("Kite config at %s is not valid JSON" % path)


def token_ready(path=DEFAULT_CONFIG, today=None):
    """True when the config holds an access token issued today (IST)."""
    try:
        cfg = load_config(path)
    except KiteError:
        return False
    today = today or _dt.datetime.now(IST).date()
    return bool(cfg.get("api_key") and cfg.get("access_token")) and cfg.get("token_date") == today.isoformat()


class Kite:
    def __init__(self, path=DEFAULT_CONFIG, cache_dir=None):
        cfg = load_config(path)
        if not cfg.get("api_key") or not cfg.get("access_token"):
            raise KiteError("Kite config has no access token: run kite_login.py")
        today = _dt.datetime.now(IST).date().isoformat()
        if cfg.get("token_date") != today:
            raise KiteError("Kite access token is from %s, Zerodha expires them daily: run kite_login.py"
                            % (cfg.get("token_date") or "an unknown day"))
        self._auth = "token %s:%s" % (cfg["api_key"], cfg["access_token"])
        self.cache_dir = cache_dir or os.path.dirname(path)
        self._last = 0.0
        self._tokens = None

    def _get(self, path, params=None, raw=False):
        wait = MIN_GAP - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"X-Kite-Version": "3", "Authorization": self._auth})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:200]
                if e.code == 429 and attempt < 2:
                    time.sleep(1.5)
                    continue
                if e.code == 403:
                    raise KiteError("Zerodha rejected the token (expired or logged out): run kite_login.py")
                raise KiteError("Kite HTTP %d: %s" % (e.code, msg))
            except (urllib.error.URLError, OSError) as e:
                if attempt == 2:
                    raise KiteError("Kite unreachable: %s" % e)
                time.sleep(1.0)
            finally:
                self._last = time.time()
        return body if raw else json.loads(body)

    def tokens(self):
        """NSE equity tradingsymbol -> instrument_token, cached for the day."""
        if self._tokens is not None:
            return self._tokens
        today = _dt.datetime.now(IST).date().isoformat()
        cache = os.path.join(self.cache_dir, "nse_instruments_%s.json" % today)
        try:
            with open(cache, encoding="utf-8") as fh:
                self._tokens = json.load(fh)
                return self._tokens
        except (OSError, ValueError):
            pass
        rows = csv.DictReader(io.StringIO(self._get("/instruments/NSE", raw=True)))
        self._tokens = {r["tradingsymbol"]: int(r["instrument_token"]) for r in rows
                        if r.get("segment") == "NSE" and r.get("instrument_type") == "EQ"}
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            for old in os.listdir(self.cache_dir):
                if old.startswith("nse_instruments_"):
                    os.remove(os.path.join(self.cache_dir, old))
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump(self._tokens, fh)
        except OSError:
            pass
        return self._tokens

    def history(self, symbol, interval, frm, to):
        """Candles -> the scanner's series shape {t, o, h, l, c, v, meta}."""
        tok = self.tokens().get(symbol)
        if tok is None:
            raise KiteError("%s is not an NSE equity on Kite" % symbol)
        doc = self._get("/instruments/historical/%d/%s" % (tok, interval),
                        {"from": frm.strftime("%Y-%m-%d %H:%M:%S"), "to": to.strftime("%Y-%m-%d %H:%M:%S")})
        return candles_to_series(((doc or {}).get("data") or {}).get("candles") or [])


def candles_to_series(candles):
    s = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "meta": {}}
    for row in candles:
        ts = _dt.datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S%z")
        s["t"].append(int(ts.timestamp()))
        for k, x in zip("ohlcv", row[1:6]):
            s[k].append(x)
    if s["c"]:
        s["meta"] = {"regularMarketPrice": s["c"][-1], "regularMarketVolume": s["v"][-1]}
    return s


def fetch_many(kite, symbols, interval, frm, to, progress):
    data, failed = {}, []
    for k, sym in enumerate(symbols):
        try:
            s = kite.history(sym, interval, frm, to)
            if s["t"]:
                data[sym] = s
            else:
                failed.append(sym)
        except KiteError as e:
            if "rejected the token" in str(e) or "unreachable" in str(e):
                raise
            failed.append(sym)
        if (k + 1) % 25 == 0 or k + 1 == len(symbols):
            progress("  %d of %d charts" % (k + 1, len(symbols)))
    return data, failed

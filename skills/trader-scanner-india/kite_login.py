#!/usr/bin/env python3
"""Daily Zerodha Kite Connect login for trader-scanner-india. Run it yourself in a
terminal, not through a chat: it handles your API secret and access token.

    python3 kite_login.py --init     # once: creates ~/.config/trader-india/kite.json (mode 600)
    python3 kite_login.py            # each trading morning: log in, save today's token
    python3 kite_login.py --check    # is today's token there?

The flow is Zerodha's own: open the login URL, sign in on kite.zerodha.com
(password + TOTP, on Zerodha's page), and Zerodha redirects to your app's
redirect URL with ?request_token=... in the address bar. Paste that whole
address (or just the token) here. The script exchanges it for an access token
with the checksum sha256(api_key + request_token + api_secret) and saves it.
"""

import argparse
import datetime as _dt
import getpass
import hashlib
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kite_data import API, DEFAULT_CONFIG, IST, token_ready  # noqa: E402


def save(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def init(path):
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    print("Kite Connect app details (from developers.kite.trade > your app).")
    key = input("API key [%s]: " % ("keep current" if cfg.get("api_key") else "required")).strip()
    secret = getpass.getpass("API secret (hidden) [%s]: " % ("keep current" if cfg.get("api_secret") else "required")).strip()
    if key:
        cfg["api_key"] = key
    if secret:
        cfg["api_secret"] = secret
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        sys.exit("Both the API key and the API secret are needed.")
    save(path, cfg)
    print("Saved to %s (readable only by you). Next: python3 kite_login.py" % path)


def login(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        sys.exit("Run python3 kite_login.py --init first.")
    print("1. Open this URL and log in on Zerodha's page:\n\n   https://kite.zerodha.com/connect/login?v=3&api_key=%s\n"
          % urllib.parse.quote(cfg["api_key"]))
    print("2. After login the browser goes to your redirect URL. Copy the whole address.")
    got = input("\nPaste the address (or the request_token): ").strip()
    if "request_token=" in got:
        got = urllib.parse.parse_qs(urllib.parse.urlparse(got).query).get("request_token", [""])[0]
    if not got:
        sys.exit("No request_token found.")
    checksum = hashlib.sha256((cfg["api_key"] + got + cfg["api_secret"]).encode()).hexdigest()
    body = urllib.parse.urlencode({"api_key": cfg["api_key"], "request_token": got, "checksum": checksum}).encode()
    req = urllib.request.Request(API + "/session/token", data=body, headers={"X-Kite-Version": "3"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())["data"]
    except urllib.error.HTTPError as e:
        sys.exit("Zerodha refused the login (%d): %s\nA request_token works once and for a few minutes: log in again."
                 % (e.code, e.read().decode("utf-8", "replace")[:200]))
    cfg["access_token"] = data["access_token"]
    cfg["token_date"] = _dt.datetime.now(IST).date().isoformat()
    cfg["user_id"] = data.get("user_id", cfg.get("user_id"))
    save(path, cfg)
    print("Logged in as %s. Token saved for today (%s). The scanner will use Kite data."
          % (cfg.get("user_id") or "you", cfg["token_date"]))


def main():
    ap = argparse.ArgumentParser(description="Zerodha Kite Connect daily login")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--init", action="store_true", help="store your API key and secret")
    ap.add_argument("--check", action="store_true", help="is today's token present?")
    a = ap.parse_args()
    if a.init:
        init(a.config)
    elif a.check:
        ok = token_ready(a.config)
        print("Kite token for today: %s" % ("yes" if ok else "no (run python3 kite_login.py)"))
        sys.exit(0 if ok else 1)
    else:
        if not os.path.exists(a.config):
            init(a.config)
        login(a.config)


if __name__ == "__main__":
    main()

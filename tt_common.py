#!/usr/bin/env python3
"""
Shared helpers for the TastyTrade pre-flight / feasibility scripts.

Credentials (environment variables)
-----------------------------------
TastyTrade decommissioned username/password sessions on 2026-02-11.  The API
now only accepts OAuth2:

  TT_CLIENT_ID      OAuth application client id   (UUID)         [fallback: TT_LOGIN]
  TT_CLIENT_SECRET  OAuth application client secret (40 hex)     [fallback: TT_PASSWORD, TT_SECRET]
  TT_REFRESH        long-lived refresh token from "Create Grant" (a JWT)

The refresh token is created once in the tastytrade web UI:
  my.tastytrade.com → Manage → My Profile → API → OAuth Applications
  → open your application → "Create Grant" → copy the refresh token.
"""
from __future__ import annotations

import os
import re
import sys
import requests

API_URL  = "https://api.tastyworks.com"
CERT_URL = "https://api.cert.tastyworks.com"
UA       = "sellvol-preflight/0.1"

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def load_credentials() -> dict:
    cid    = os.environ.get("TT_CLIENT_ID") or os.environ.get("TT_LOGIN", "")
    secret = (os.environ.get("TT_CLIENT_SECRET") or os.environ.get("TT_SECRET")
              or os.environ.get("TT_PASSWORD", ""))
    refresh = os.environ.get("TT_REFRESH", "")
    return {"client_id": cid.strip(), "client_secret": secret.strip(),
            "refresh_token": refresh.strip()}


def describe_credentials(c: dict) -> list[str]:
    """Human-readable, value-free diagnosis of what the env vars look like."""
    out = []
    cid, sec, ref = c["client_id"], c["client_secret"], c["refresh_token"]
    if not cid:
        out.append("client id      : MISSING (set TT_CLIENT_ID)")
    elif UUID_RE.fullmatch(cid):
        out.append("client id      : present, UUID format  → looks like an OAuth client id ✔")
    elif "@" in cid:
        out.append("client id      : looks like an e-mail / username → legacy login, NOT usable (decommissioned 2026-02-11)")
    else:
        out.append(f"client id      : present ({len(cid)} chars, unexpected format)")
    if not sec:
        out.append("client secret  : MISSING (set TT_CLIENT_SECRET)")
    elif re.fullmatch(r"[0-9a-f]{40}", sec):
        out.append("client secret  : present, 40-char hex  → looks like an OAuth client secret ✔")
    else:
        out.append(f"client secret  : present ({len(sec)} chars)")
    if not ref:
        out.append("refresh token  : MISSING (set TT_REFRESH)  ← this is what blocks login")
    elif ref.count(".") == 2:
        out.append("refresh token  : present, JWT format ✔")
    else:
        out.append(f"refresh token  : present ({len(ref)} chars) but not JWT-shaped — check it")
    return out


def get_access_token(c: dict, sandbox: bool = False) -> tuple[str | None, str]:
    """Exchange the refresh token for a 15-minute access token. Returns (token, message)."""
    if not c["refresh_token"]:
        return None, "no refresh token"
    base = CERT_URL if sandbox else API_URL
    r = requests.post(f"{base}/oauth/token",
                      data={"grant_type": "refresh_token",
                            "client_id": c["client_id"],
                            "client_secret": c["client_secret"],
                            "refresh_token": c["refresh_token"]},
                      headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    return r.json().get("access_token"), "ok"


def print_refresh_token_instructions() -> None:
    print("""
HOW TO UNBLOCK (one-time, ~2 minutes, done by the account owner in a browser):
  1. Log in at https://my.tastytrade.com
  2. Manage → My Profile → API → OAuth Applications
  3. Open the application whose Client ID matches TT_LOGIN
     (if none exists: "Create OAuth Application", scopes: read, trade, openid;
      then store the new Client Secret as TT_CLIENT_SECRET — it is shown once).
  4. Click "Create Grant" → copy the refresh token (long JWT, never expires).
  5. Add it to this environment as  TT_REFRESH=<token>  and re-run:
        python3 preflight.py
""")


def die(msg: str, code: int = 2) -> None:
    print(f"\n✖ {msg}")
    sys.exit(code)

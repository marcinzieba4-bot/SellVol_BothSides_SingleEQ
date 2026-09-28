#!/usr/bin/env python3
"""Core library for the tastytrade dispersion bot (see README.md).

Covers: auth, chain/strike selection by delta, dry-run margin pre-check,
multi-leg order placement with mid-walking, book-delta computation, and the
three entry points (roll / hedge / monitor). Credentials come from env vars
TT_LOGIN / TT_PASSWORD (or an OAuth token in TT_TOKEN); never hardcode them.

Run against the sandbox (api.cert.tastyworks.com) until fills, sizing and
margin numbers are verified end to end.
"""
import json
import math
import os
import time
from dataclasses import dataclass

import requests
import yaml

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "config.yaml")))
BASE = "https://api.cert.tastyworks.com" if CFG.get("sandbox", True) else "https://api.tastyworks.com"


# ── session ──────────────────────────────────────────────────────────────────
class TT:
    def __init__(self):
        self.s = requests.Session()
        tok = os.environ.get("TT_TOKEN")
        if tok:
            self.s.headers["Authorization"] = tok
        else:
            r = self.s.post(f"{BASE}/sessions", json={
                "login": os.environ["TT_LOGIN"],
                "password": os.environ["TT_PASSWORD"],
                "remember-me": True})
            r.raise_for_status()
            self.s.headers["Authorization"] = r.json()["data"]["session-token"]
        accts = self.get("/customers/me/accounts")["data"]["items"]
        self.acct = accts[0]["account"]["account-number"]

    def get(self, path, **kw):
        r = self.s.get(BASE + path, **kw); r.raise_for_status(); return r.json()

    def post(self, path, body):
        r = self.s.post(BASE + path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"{path}: {r.status_code} {r.text[:400]}")
        return r.json()


# ── market data ──────────────────────────────────────────────────────────────
def nested_chain(tt, sym):
    """Nearest monthly expiration 25-40 DTE with its strike list."""
    ch = tt.get(f"/option-chains/{sym}/nested")["data"]["items"][0]
    exps = [e for e in ch["expirations"]
            if 25 <= int(e["days-to-expiration"]) <= 40
            and e["expiration-type"] == "Regular"]
    exps.sort(key=lambda e: int(e["days-to-expiration"]))
    return exps[0]


def strike_by_delta(exp, spot, iv, target_delta, dte):
    """Pick the listed strike nearest the Black-Scholes target-delta strike.

    iv comes from DXLink Greeks (production) or, offline, from the VolVue
    calibration; d1 = -N^{-1}(delta) for calls.
    """
    from statistics import NormalDist
    nd = NormalDist()
    s = iv * math.sqrt(dte / 365)
    k_target = spot * math.exp(-nd.inv_cdf(target_delta) * s + s * s / 2)
    strikes = [float(st["strike-price"]) for st in exp["strikes"]]
    return min(strikes, key=lambda k: abs(k - k_target)), \
        {float(st["strike-price"]): st for st in exp["strikes"]}


# ── orders ───────────────────────────────────────────────────────────────────
@dataclass
class Leg:
    symbol: str          # OCC option symbol from the chain ("symbol" field)
    action: str          # Buy to Open / Sell to Open / Buy to Close / Sell to Close
    quantity: int
    instrument: str = "Equity Option"


def order_body(legs, price, effect):
    return {"order-type": "Limit", "time-in-force": "Day",
            "price": f"{abs(price):.2f}", "price-effect": effect,
            "legs": [{"instrument-type": l.instrument, "symbol": l.symbol,
                      "action": l.action, "quantity": l.quantity} for l in legs]}


def dry_run_ok(tt, body, max_margin_frac):
    """Margin pre-check: reject the order if projected usage exceeds the cap."""
    r = tt.post(f"/accounts/{tt.acct}/orders/dry-run", body)
    bal = tt.get(f"/accounts/{tt.acct}/balances")["data"]
    eq = float(bal["net-liquidating-value"])
    bp_effect = abs(float(r["data"]["buying-power-effect"]["change-in-margin-requirement"]))
    used = float(bal["maintenance-requirement"])
    return (used + bp_effect) <= max_margin_frac * eq, bp_effect


def place_walking(tt, legs, mid, half_spread, effect, steps=3, wait=20):
    """Limit at mid, walked toward the far side in 20% increments."""
    for i in range(steps + 1):
        px = mid + (half_spread * 0.2 * i) * (1 if effect == "Debit" else -1)
        body = order_body(legs, px, effect)
        resp = tt.post(f"/accounts/{tt.acct}/orders", body)
        oid = resp["data"]["order"]["id"]
        time.sleep(wait)
        st = tt.get(f"/accounts/{tt.acct}/orders/{oid}")["data"]["status"]
        if st in ("Filled",):
            return oid
        tt.s.delete(f"{BASE}/accounts/{tt.acct}/orders/{oid}")
    return None


# ── book construction (roll.py entry point) ──────────────────────────────────
def monthly_roll(tt, universe, spot, ivs):
    """Close expiring cohort, size from CURRENT equity, open the new book.

    universe: list of tickers (already rotated/filtered for granularity)
    spot/ivs: dicts symbol -> spot price / 30d IV (DXLink or fallback feed)
    """
    cfg = CFG
    bal = tt.get(f"/accounts/{tt.acct}/balances")["data"]
    equity = float(bal["net-liquidating-value"])
    L = cfg["leverage"]
    per_name = 0.9 * L * equity / len(universe)

    for t in universe:
        exp = nested_chain(tt, t)
        dte = int(exp["days-to-expiration"])
        k30, table = strike_by_delta(exp, spot[t], ivs[t], cfg["deltas"]["long"], dte)
        k10, _ = strike_by_delta(exp, spot[t], ivs[t], cfg["deltas"]["wing"], dte)
        n = max(1, round(per_name / (100 * spot[t])))
        if 100 * spot[t] > 2 * per_name:      # granularity cutoff
            continue
        legs = [Leg(table[k30]["call"], "Buy to Open", n),
                Leg(table[k10]["call"], "Sell to Open", n)]
        # mid/half_spread from DXLink Quote events for both legs (net):
        mid, half = quote_vertical(tt, table[k30], table[k10])
        body = order_body(legs, mid, "Debit")
        ok, _ = dry_run_ok(tt, body, cfg["max_margin_frac"])
        if ok:
            place_walking(tt, legs, mid, half, "Debit")

    # short SPY leg, notional-matched
    exp = nested_chain(tt, "SPY")
    dte = int(exp["days-to-expiration"])
    kS, table = strike_by_delta(exp, spot["SPY"], ivs["SPY"], cfg["deltas"]["spy_short"], dte)
    nS = max(1, round(0.9 * L * equity / (100 * spot["SPY"])))
    legs = [Leg(table[kS]["call"], "Sell to Open", nS)]
    if cfg["account_mode"] == "regt":
        kW, _ = strike_by_delta(exp, spot["SPY"], ivs["SPY"], cfg["deltas"]["spy_wing"], dte)
        legs.append(Leg(table[kW]["call"], "Buy to Open", nS))
    mid, half = quote_vertical(tt, table[kS], None)
    body = order_body(legs, mid, "Credit")
    ok, bp = dry_run_ok(tt, body, cfg["max_margin_frac"])
    if not ok:
        raise RuntimeError(f"SPY leg fails margin pre-check (bp effect {bp:.0f}) - lower leverage")
    place_walking(tt, legs, mid, half, "Credit")


# ── weekly hedge (hedge.py entry point) ──────────────────────────────────────
def weekly_hedge(tt, greeks):
    """greeks: dict occ-symbol -> delta from the DXLink Greeks stream."""
    pos = tt.get(f"/accounts/{tt.acct}/positions")["data"]["items"]
    book_delta_sh = 0.0          # in SPY-share equivalents
    spy_px = greeks["SPY"]["price"]
    for p in pos:
        if p["instrument-type"] == "Equity Option":
            sgn = 1 if p["quantity-direction"] == "Long" else -1
            d = greeks[p["symbol"]]["delta"]
            und_px = greeks[p["symbol"]]["underlying-price"]
            book_delta_sh += sgn * int(p["quantity"]) * 100 * d * und_px / spy_px
        elif p["instrument-type"] == "Equity" and p["symbol"] == "SPY":
            sgn = 1 if p["quantity-direction"] == "Long" else -1
            book_delta_sh += sgn * int(p["quantity"])
    target_trade = -round(book_delta_sh)
    if abs(target_trade) * spy_px < 2000:     # ignore dust
        return
    action = "Buy to Open" if target_trade > 0 else "Sell to Open"
    legs = [Leg("SPY", action, abs(target_trade), instrument="Equity")]
    body = order_body(legs, spy_px, "Debit" if target_trade > 0 else "Credit")
    tt.post(f"/accounts/{tt.acct}/orders", body)


def quote_vertical(tt, long_strike, short_strike):
    """Net mid and half-spread for a vertical from DXLink Quote events.

    Production: subscribe to both legs' streamer-symbols via the DXLink
    websocket (GET /api-quote-tokens for the URL+token) and combine bids/asks.
    Placeholder here; sandbox returns synthetic quotes.
    """
    raise NotImplementedError("wire to DXLink quote stream")


if __name__ == "__main__":
    import sys
    tt = TT()
    print("account:", tt.acct, "| sandbox:", CFG.get("sandbox", True))
    print("balances:", json.dumps(tt.get(f"/accounts/{tt.acct}/balances")["data"], indent=1)[:600])

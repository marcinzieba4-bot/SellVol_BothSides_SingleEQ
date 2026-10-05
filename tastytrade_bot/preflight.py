#!/usr/bin/env python3
"""$5k account preflight: verify the strategy's mechanics are allowed, cheaply.

Usage:
  python3 preflight.py            # read-only + dry-runs (no orders placed)
  python3 preflight.py --live     # additionally: one tiny real round-trip
                                  # (buy 1 cheap-name call vertical, sell it back)

Reads TT_LOGIN/TT_PASSWORD or TT_TOKEN from the environment. Runs against
PRODUCTION (the funded account) - dry-runs are server-side simulations and
place nothing; only --live trades, and only a single 1-contract defined-risk
vertical on the cheapest liquid name (~$30-80 debit, ~$5-20 round-trip cost).

Checks, in order:
  1. auth + account discovery + balances
  2. trading status: options level, futures approval, PM flag
  3. SPY chain: nearest monthly expiry, 30d + 1d strikes listed?
  4. dry-run: 1x cheap-name 30/10 debit vertical  (long-leg mechanics)
  5. dry-run: 1x SPY 30/1 credit spread           (spy_regt short leg)
  6. dry-run: sell 1 MES 30d call                 (es_span short leg, if futures)
  7. [--live] place the vertical at mid, walk up to fill, then close it
"""
import json
import math
import os
import sys
import time
from statistics import NormalDist

import requests

BASE = "https://api.tastyworks.com"
ND = NormalDist()
LIVE = "--live" in sys.argv


def login():
    s = requests.Session()
    s.headers["User-Agent"] = "dispersion-preflight/1.0"
    tok = os.environ.get("TT_TOKEN")
    if tok:
        s.headers["Authorization"] = tok
    else:
        r = s.post(f"{BASE}/sessions", json={
            "login": os.environ["TT_LOGIN"],
            "password": os.environ["TT_PASSWORD"],
            "remember-me": True})
        if r.status_code >= 400:
            sys.exit(f"LOGIN FAILED: {r.status_code} {r.text[:300]}")
        s.headers["Authorization"] = r.json()["data"]["session-token"]
    return s


def get(s, path, params=None):
    r = s.get(BASE + path, params=params)
    if r.status_code >= 400:
        return {"_error": f"{r.status_code} {r.text[:300]}"}
    return r.json()


def post(s, path, body):
    r = s.post(BASE + path, json=body)
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:300]}
    j["_status"] = r.status_code
    return j


def bs_call(spot, k, iv, t):
    sq = iv * math.sqrt(t)
    d1 = (math.log(spot / k) + sq * sq / 2) / sq
    return spot * ND.cdf(d1) - k * ND.cdf(d1 - sq)


def delta_strike(strikes, spot, iv, t, delta):
    sq = iv * math.sqrt(t)
    k_t = spot * math.exp(-ND.inv_cdf(delta) * sq + sq * sq / 2)
    return min(strikes, key=lambda k: abs(k - k_t))


def pick_chain(s, sym):
    ch = get(s, f"/option-chains/{sym}/nested")
    if "_error" in ch:
        return None, ch["_error"]
    exps = [e for e in ch["data"]["items"][0]["expirations"]
            if 20 <= int(e["days-to-expiration"]) <= 45]
    if not exps:
        return None, "no 20-45 DTE expiration"
    exps.sort(key=lambda e: int(e["days-to-expiration"]))
    return exps[0], None


def iv30(s, sym):
    m = get(s, "/market-metrics", params={"symbols": sym})
    try:
        return float(m["data"]["items"][0]["implied-volatility-index"])
    except Exception:
        return None


def order(legs, price, effect, tif="Day"):
    return {"order-type": "Limit", "time-in-force": tif,
            "price": f"{abs(price):.2f}", "price-effect": effect, "legs": legs}


def leg(sym, action, qty, itype="Equity Option"):
    return {"instrument-type": itype, "symbol": sym, "action": action, "quantity": qty}


def dry(s, acct, body, label):
    r = post(s, f"/accounts/{acct}/orders/dry-run", body)
    if r["_status"] < 400:
        bpe = r["data"].get("buying-power-effect", {})
        warn = [w.get("message", "") for w in r["data"].get("warnings", [])]
        print(f"  [OK ] {label}: margin effect "
              f"{bpe.get('change-in-margin-requirement', '?')} "
              f"{'| ' + '; '.join(warn) if warn else ''}")
        return True
    err = r.get("error", {})
    print(f"  [FAIL] {label}: {err.get('code', r['_status'])} "
          f"{err.get('message', '')[:200]}")
    for e in err.get("errors", [])[:3]:
        print(f"         - {e.get('code','')} {e.get('message','')[:150]}")
    return False


def main():
    s = login()
    me = get(s, "/customers/me/accounts")["data"]["items"]
    acct = me[0]["account"]["account-number"]
    margin_type = me[0]["account"].get("margin-or-cash")
    print(f"1. auth OK | account {acct} ({margin_type})")

    bal = get(s, f"/accounts/{acct}/balances")["data"]
    print(f"   equity ${float(bal['net-liquidating-value']):,.0f} | "
          f"option BP ${float(bal.get('equity-buying-power', 0)):,.0f} | "
          f"maint req ${float(bal.get('maintenance-requirement', 0)):,.0f}")

    ts = get(s, f"/accounts/{acct}/trading-status")["data"]
    print(f"2. options level: {ts.get('options-level')} | futures approved: "
          f"{ts.get('is-futures-approved')} | PM: {ts.get('is-portfolio-margin-enabled')} | "
          f"closing-only: {ts.get('is-closing-only')}")

    # 3. SPY chain
    exp, err = pick_chain(s, "SPY")
    ivS = iv30(s, "SPY") or 0.15
    spotS = None
    if exp:
        strikes = sorted(float(st["strike-price"]) for st in exp["strikes"])
        table = {float(st["strike-price"]): st for st in exp["strikes"]}
        # spot approx from chain midpoint of strikes near the money is unreliable;
        # use market-metrics' beta-adjusted fields if present, else ask user side.
        spotS = float(get(s, "/market-metrics", params={"symbols": "SPY"})
                      ["data"]["items"][0].get("updated-at-price") or 0) or None
        if spotS is None:
            spotS = strikes[len(strikes) // 2]
        t = int(exp["days-to-expiration"]) / 365
        k30 = delta_strike(strikes, spotS, ivS, t, 0.30)
        k01 = delta_strike(strikes, spotS, ivS, t, 0.01)
        print(f"3. SPY {exp['expiration-date']} ({exp['days-to-expiration']} DTE): "
              f"30d strike {k30}, 1d strike {k01} "
              f"(chain spans {strikes[0]}-{strikes[-1]}; 1d listed: {k01 < strikes[-1]})")
    else:
        print(f"3. SPY chain FAILED: {err}"); return

    # 4. cheap liquid name vertical (dry-run)
    CHEAP = ["INTC", "F", "PFE", "T", "CSCO", "WFC", "KO"]
    pick = None
    for c in CHEAP:
        e2, err2 = pick_chain(s, c)
        if e2:
            pick = (c, e2); break
    name, expC = pick
    ivC = iv30(s, name) or 0.35
    strikesC = sorted(float(st["strike-price"]) for st in expC["strikes"])
    tableC = {float(st["strike-price"]): st for st in expC["strikes"]}
    spotC = float(get(s, "/market-metrics", params={"symbols": name})
                  ["data"]["items"][0].get("updated-at-price") or strikesC[len(strikesC)//2])
    tC = int(expC["days-to-expiration"]) / 365
    kL = delta_strike(strikesC, spotC, ivC, tC, 0.30)
    kW = delta_strike(strikesC, spotC, ivC, tC, 0.10)
    if kW == kL:
        kW = min(k for k in strikesC if k > kL)
    mid_est = (bs_call(spotC, kL, ivC, tC) - bs_call(spotC, kW, ivC, tC))
    legsV = [leg(tableC[kL]["call"], "Buy to Open", 1),
             leg(tableC[kW]["call"], "Sell to Open", 1)]
    bodyV = order(legsV, mid_est, "Debit")
    print(f"4. test vertical: {name} {expC['expiration-date']} {kL}/{kW} call spread, "
          f"est. debit ${mid_est*100:.0f}")
    ok4 = dry(s, acct, bodyV, f"{name} 30/10 debit vertical x1")

    # 5. SPY 30/1 credit spread (dry-run)
    midS = bs_call(spotS, k30, ivS, t) - bs_call(spotS, k01, ivS, t)
    legs5 = [leg(table[k30]["call"], "Sell to Open", 1),
             leg(table[k01]["call"], "Buy to Open", 1)]
    dry(s, acct, order(legs5, midS, "Credit"), "SPY 30/1 credit spread x1 (spy_regt leg)")

    # 6. MES short call (dry-run; futures symbols like ./MESZ6 EW4V6 ...)
    if ts.get("is-futures-approved"):
        fch = get(s, "/futures-option-chains/MES/nested")
        if "_error" not in fch:
            print("  [OK ] MES futures option chain reachable (es_span leg available)")
        else:
            print(f"  [FAIL] MES chain: {fch['_error']}")
    else:
        print("  [SKIP] futures not approved on this account yet -> es_span leg "
              "unavailable until you enable futures trading (The Works)")

    # 7. live round-trip
    if not LIVE:
        print("\nDry-run complete. Re-run with --live for the tiny real round-trip.")
        return
    if not ok4:
        print("\nSkipping live test: the vertical failed its dry-run."); return
    print(f"\n7. LIVE: buying 1 {name} {kL}/{kW} vertical (max cost ~${mid_est*100+15:.0f})")
    oid = walk(s, acct, legsV, mid_est, "Debit")
    if not oid:
        print("   no fill after walking - cancelled, nothing held"); return
    print(f"   filled, order {oid}. Closing...")
    legsC = [leg(tableC[kL]["call"], "Sell to Close", 1),
             leg(tableC[kW]["call"], "Buy to Close", 1)]
    oid2 = walk(s, acct, legsC, mid_est, "Credit")
    print(f"   closed (order {oid2})" if oid2 else
          "   CLOSE NOT FILLED - position still open, close manually or re-run close")


def walk(s, acct, legs, mid, effect, steps=4, wait=15):
    for i in range(steps + 1):
        px = mid * (1 + 0.04 * i * (1 if effect == "Debit" else -1))
        r = post(s, f"/accounts/{acct}/orders", order(legs, px, effect))
        if r["_status"] >= 400:
            print(f"   order rejected: {json.dumps(r.get('error', {}))[:250]}")
            return None
        oid = r["data"]["order"]["id"]
        time.sleep(wait)
        st = get(s, f"/accounts/{acct}/orders/{oid}")["data"]["status"]
        if st == "Filled":
            return oid
        requests.delete(f"{BASE}/accounts/{acct}/orders/{oid}", headers=s.headers)
    return None


if __name__ == "__main__":
    main()

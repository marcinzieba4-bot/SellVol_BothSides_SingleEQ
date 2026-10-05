#!/usr/bin/env python3
"""
LIVE feasibility check at TastyTrade (run during US market hours).

For every name in the universe (default 2026.txt, top-100 S&P 500):
  • spot (mark), ATM strike for the expiration closest to 30 DTE
  • put & call mid, bid/ask spread, premium as % of spot
  • IV30, IV rank, tastytrade liquidity rating
  • optional: dry-run SELL 1 ATM put → real buying-power effect (no order placed)
  • contract granularity vs the backtest's "1 unit = 1 % of capital" rule

Compares live premiums with what the backtest assumed (history.csv, 2022+).

Usage:
  python3 feasibility_live.py                       # capital = account net-liq
  python3 feasibility_live.py --capital 2000000     # assume a capital base
  python3 feasibility_live.py --dry-run-limit 100   # BP dry-runs for all names (default 25)
  python3 feasibility_live.py --no-dry-run
Requires TT_CLIENT_SECRET (or TT_PASSWORD) and TT_REFRESH — see tt_common.py.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import date
from decimal import Decimal

import pandas as pd

from tt_common import (load_credentials, describe_credentials, print_refresh_token_instructions,
                       refresh_token_usable)

TARGET_DTE = 30
REGT_ATM   = 0.20


def load_universe(path: str) -> list[str]:
    ts = [re.search(r"\(([^)]+)\)", l).group(1) for l in open(path) if re.search(r"\(([^)]+)\)", l)]
    return ts


def tt_symbol(t: str) -> str:
    # tastytrade equity symbol for Berkshire B is "BRK/B"
    return t.replace("BRK.B", "BRK/B").replace("BRK-B", "BRK/B")


def f(x):
    return None if x is None else float(x)


def mid(q):
    if q is None:
        return None, None
    if q.bid is not None and q.ask is not None and q.ask > 0:
        return float((q.bid + q.ask) / 2), float(q.ask - q.bid)
    return f(q.mark), None


async def run(a) -> int:

    c = load_credentials()
    if not refresh_token_usable(c):
        print("\n".join(describe_credentials(c)))
        print_refresh_token_instructions()
        return 2

    # SDK import only once credentials are present (see preflight.py).
    from tastytrade import Session, Account
    from tastytrade.instruments import NestedOptionChain
    from tastytrade.market_data import get_market_data_by_type
    from tastytrade.market_sessions import get_market_sessions, ExchangeType
    from tastytrade.metrics import get_market_metrics
    from tastytrade.order import LimitOrder, Leg, OrderAction, InstrumentType, OrderTimeInForce

    tickers = load_universe(a.universe)
    symbols = [tt_symbol(t) for t in tickers]
    rows: list[dict] = []

    async with Session(provider_secret=c["client_secret"], refresh_token=c["refresh_token"],
                       is_test=a.sandbox) as sess:
        accounts = await Account.get(sess)
        acct = accounts[0] if accounts else None
        capital = a.capital
        if acct:
            bal = await acct.get_balances(sess)
            print(f"Account {acct.account_number}: net-liq ${float(bal.net_liquidating_value):,.0f}, "
                  f"derivative BP ${float(bal.derivative_buying_power):,.0f}")
            if capital is None:
                capital = float(bal.net_liquidating_value)
        capital = capital or 1_000_000.0
        unit = capital / 100
        print(f"Capital base ${capital:,.0f} → 1 unit = ${unit:,.0f} notional per name")

        ms = await get_market_sessions(sess, [ExchangeType.NYSE])
        print(f"NYSE session: status={ms[0].status}  (quotes are only meaningful while Open)")

        # spot for all names (≤100 per call)
        spots: dict[str, float] = {}
        for i in range(0, len(symbols), 100):
            for q in await get_market_data_by_type(sess, equities=symbols[i:i + 100]):
                spots[q.symbol] = f(q.mark) or f(q.last) or f(q.close)

        metrics = {}
        try:
            for i in range(0, len(symbols), 50):
                for m in await get_market_metrics(sess, symbols[i:i + 50]):
                    metrics[m.symbol] = m
        except Exception as e:
            print("market metrics failed:", repr(e)[:120])

        # chains → ATM put/call symbols
        opt_syms: list[str] = []
        meta: dict[str, dict] = {}
        for sym in symbols:
            spot = spots.get(sym)
            try:
                chain = (await NestedOptionChain.get(sess, sym))[0]
                exps = [e for e in chain.expirations if e.days_to_expiration >= 7]
                exp = min(exps, key=lambda e: abs(e.days_to_expiration - TARGET_DTE))
                if spot is None:
                    spot = float(exp.strikes[len(exp.strikes) // 2].strike_price)
                strike = min(exp.strikes, key=lambda s: abs(float(s.strike_price) - spot))
                meta[sym] = {"spot": spot, "exp": exp.expiration_date, "dte": exp.days_to_expiration,
                             "strike": float(strike.strike_price), "put": strike.put, "call": strike.call}
                opt_syms += [strike.put, strike.call]
            except Exception as e:
                meta[sym] = {"spot": spot, "error": repr(e)[:100]}
            await asyncio.sleep(0.05)

        quotes = {}
        for i in range(0, len(opt_syms), 100):
            for q in await get_market_data_by_type(sess, options=opt_syms[i:i + 100]):
                quotes[q.symbol] = q

        # dry-runs for buying power (real margin engine, nothing placed)
        bp: dict[str, dict] = {}
        if acct and not a.no_dry_run:
            n = 0
            for sym in symbols:
                m = meta.get(sym, {})
                if "put" not in m or n >= a.dry_run_limit:
                    continue
                pm, _ = mid(quotes.get(m["put"]))
                # tastytrade pre-flight rejects prices off the tick grid: $0.05 below $3, $0.10 above
                # (penny-pilot names accept finer ticks, but these are valid everywhere)
                tick = 0.05 if (pm or 1.0) < 3 else 0.10
                px_ok = round(round((pm or 1.0) / tick) * tick, 2)
                try:
                    order = LimitOrder(time_in_force=OrderTimeInForce.DAY, price=Decimal(str(px_ok)),
                                       legs=[Leg(instrument_type=InstrumentType.EQUITY_OPTION, symbol=m["put"],
                                                 action=OrderAction.SELL_TO_OPEN, quantity=1)])
                    e = await acct.get_order_buying_power_effect(sess, order)
                    bp[sym] = {"bp_change": float(e.change_in_buying_power),
                               "isolated_margin": float(e.isolated_order_margin_requirement)}
                except Exception as ex:
                    # the SDK raises KeyError('data') on a 422 pre-flight rejection; fetch the real message
                    msg = repr(ex)[:100]
                    try:
                        await sess.refresh()
                        r = await sess._client.post(f"/accounts/{acct.account_number}/orders/dry-run",
                                                    data=order.model_dump_json(exclude_none=True, by_alias=True))
                        msg = f"HTTP {r.status_code}: {r.text[:140]}"
                    except Exception:
                        pass
                    bp[sym] = {"error": msg}
                n += 1
                await asyncio.sleep(0.1)

    # backtest reference premiums
    hist = pd.read_csv("history.csv", parse_dates=["date"])
    ref = hist[(hist.date >= "2022") & (hist.prem_pct > 0)].groupby("ticker").prem_pct.mean()   # skip months carry prem_pct=0

    for t, sym in zip(tickers, symbols):
        m = meta.get(sym, {})
        spot = m.get("spot")
        pq, cq = quotes.get(m.get("put")), quotes.get(m.get("call"))
        pm, pspread = mid(pq)
        cm, cspread = mid(cq)
        notional = spot * 100 if spot else None
        row = {
            "ticker": t, "spot": spot, "expiration": m.get("exp"), "dte": m.get("dte"), "strike": m.get("strike"),
            "put_mid": pm, "put_bid": f(getattr(pq, "bid", None)), "put_ask": f(getattr(pq, "ask", None)),
            "put_prem_pct": (pm / spot * 100) if (pm and spot) else None,
            "put_spread_pct_of_mid": (pspread / pm * 100) if (pspread is not None and pm) else None,
            "call_mid": cm, "call_prem_pct": (cm / spot * 100) if (cm and spot) else None,
            "backtest_prem_pct_2022plus": f(ref.get(t.replace("/", "-"))) if t.replace("/", "-") in ref.index else None,
            "iv30": f(getattr(metrics.get(sym), "implied_volatility_30_day", None)),
            "iv_rank": getattr(metrics.get(sym), "implied_volatility_index_rank", None),
            "liquidity_rating": getattr(metrics.get(sym), "liquidity_rating", None),
            "contract_notional": notional,
            "contracts_at_size1": int(unit // notional) if notional else None,
            "min_capital_for_1_unit": spot * 10_000 if spot else None,
            "regT_est_bp": notional * REGT_ATM if notional else None,
            "tt_bp_change": bp.get(sym, {}).get("bp_change"),
            "tt_bp_pct_of_notional": (abs(bp[sym]["bp_change"]) / notional * 100) if (sym in bp and "bp_change" in bp[sym] and notional) else None,
            "error": m.get("error") or bp.get(sym, {}).get("error"),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    out = f"feasibility_live_{date.today()}.csv"
    df.to_csv(out, index=False)

    ok = df.dropna(subset=["put_prem_pct"])
    print("\n══════════ LIVE FEASIBILITY SUMMARY ══════════")
    print(f"names with live ATM quotes       : {len(ok)} / {len(df)}")
    print(f"ATM put premium  (% spot, ~{TARGET_DTE} DTE): mean {ok.put_prem_pct.mean():.2f}  median {ok.put_prem_pct.median():.2f}  "
          f"min {ok.put_prem_pct.min():.2f}  max {ok.put_prem_pct.max():.2f}")
    print(f"ATM call premium (% spot)        : mean {ok.call_prem_pct.mean():.2f}")
    both = ok.dropna(subset=["backtest_prem_pct_2022plus"])
    if len(both):
        print(f"backtest assumed (2022+ mean)    : {both.backtest_prem_pct_2022plus.mean():.2f}%  →  live/backtest ratio "
              f"{(both.put_prem_pct / both.backtest_prem_pct_2022plus).median():.2f}x (median)")
    print(f"bid-ask spread (% of mid)        : median {ok.put_spread_pct_of_mid.median():.1f}%  "
          f"p90 {ok.put_spread_pct_of_mid.quantile(.9):.1f}%  ← slippage eats this/2 of premium if hitting the bid")
    print(f"liquidity rating (1 worst..4 best): {ok.liquidity_rating.value_counts().sort_index().to_dict()}")
    print(f"names tradable at size 1 with ${capital:,.0f}: {(ok.contracts_at_size1 >= 1).sum()} / {len(ok)}")
    print(f"capital for every name ≥1 contract : ${ok.min_capital_for_1_unit.max():,.0f}")
    bpok = ok.dropna(subset=["tt_bp_pct_of_notional"])
    if len(bpok):
        print(f"tastytrade BP for 1 naked ATM put : median {bpok.tt_bp_pct_of_notional.median():.1f}% of notional  "
              f"(Reg-T estimate {REGT_ATM*100:.0f}%), n={len(bpok)}")
        print(f"BP to hold 1 contract on every quoted name: ${bpok.tt_bp_change.abs().sum():,.0f} (for the {len(bpok)} dry-run names)")
    print(f"\nPer-name table → {out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="2026.txt")
    ap.add_argument("--capital", type=float, default=None, help="capital base; default = account net-liq")
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--dry-run-limit", type=int, default=25)
    ap.add_argument("--no-dry-run", action="store_true")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()

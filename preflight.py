#!/usr/bin/env python3
"""
TastyTrade pre-flight check for the SellVol single-equity strategy.

Runs BEFORE market hours and answers:
  1. Can we authenticate at all?            (OAuth2 refresh-token exchange)
  2. Which account(s), what options level, margin type, portfolio margin?
  3. Net-liq, derivative buying power, Reg-T requirement right now.
  4. Is market data reachable (equity quote, nested option chain, option quotes)?
  5. What does ONE naked ATM ~30-DTE put on a sample name cost in buying power?
     (dry-run only — nothing is sent to the market)

Usage:
  python3 preflight.py                 # production
  python3 preflight.py --sandbox       # api.cert.tastyworks.com
  python3 preflight.py --sample NVDA   # sample underlying for chain / dry-run

Exit codes: 0 all checks passed, 1 a check failed, 2 cannot authenticate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from decimal import Decimal

from tt_common import (load_credentials, describe_credentials, get_access_token,
                       print_refresh_token_instructions, die)

REPORT = "preflight_report.json"


def _d(x):
    return float(x) if isinstance(x, Decimal) else x


async def run(args) -> int:
    from tastytrade import Session, Account
    from tastytrade.instruments import NestedOptionChain
    from tastytrade.market_data import get_market_data_by_type
    from tastytrade.market_sessions import get_market_sessions, ExchangeType
    from tastytrade.metrics import get_market_metrics
    from tastytrade.order import LimitOrder, Leg, OrderAction, InstrumentType, OrderTimeInForce

    report: dict = {"date": str(date.today()), "sandbox": args.sandbox, "checks": {}}
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok = ok and passed
        report["checks"][name] = {"passed": passed, "detail": detail}
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}{(': ' + detail) if detail else ''}")

    c = load_credentials()
    print("\n── 0. Credentials ─────────────────────────────────────────────")
    for line in describe_credentials(c):
        print("  " + line)
    if not c["refresh_token"]:
        print("\n  Legacy /sessions login with TT_LOGIN/TT_PASSWORD → 401 invalid_credentials")
        print("  (username/password sessions were decommissioned by tastytrade on 2026-02-11).")
        print_refresh_token_instructions()
        report["checks"]["auth"] = {"passed": False, "detail": "TT_REFRESH missing"}
        json.dump(report, open(REPORT, "w"), indent=1)
        return 2

    print("\n── 1. OAuth token exchange ────────────────────────────────────")
    token, msg = get_access_token(c, sandbox=args.sandbox)
    check("oauth_token", token is not None, msg)
    if token is None:
        print_refresh_token_instructions()
        json.dump(report, open(REPORT, "w"), indent=1)
        return 2

    async with Session(provider_secret=c["client_secret"], refresh_token=c["refresh_token"],
                       is_test=args.sandbox) as sess:
        print("\n── 2. Customer & accounts ─────────────────────────────────────")
        cust = await sess.get_customer()
        check("customer", True, f"id={cust.id}")
        accounts = await Account.get(sess)
        check("accounts", len(accounts) > 0, f"{len(accounts)} account(s)")
        report["accounts"] = []

        for acct in accounts:
            print(f"\n  Account {acct.account_number}  ({acct.account_type_name}, margin_or_cash={acct.margin_or_cash})")
            ts  = await acct.get_trading_status(sess)
            bal = await acct.get_balances(sess)
            info = {
                "account_number": acct.account_number,
                "type": acct.account_type_name,
                "margin_or_cash": acct.margin_or_cash,
                "options_level": ts.options_level,
                "equities_margin_calculation_type": ts.equities_margin_calculation_type,
                "is_portfolio_margin_enabled": ts.is_portfolio_margin_enabled,
                "is_in_margin_call": ts.is_in_margin_call,
                "net_liquidating_value": _d(bal.net_liquidating_value),
                "cash_balance": _d(bal.cash_balance),
                "derivative_buying_power": _d(bal.derivative_buying_power),
                "equity_buying_power": _d(bal.equity_buying_power),
                "used_derivative_buying_power": _d(bal.used_derivative_buying_power),
                "reg_t_margin_requirement": _d(bal.reg_t_margin_requirement),
                "margin_equity": _d(bal.margin_equity),
            }
            report["accounts"].append(info)
            for k, v in info.items():
                print(f"    {k:34s}: {v}")
            naked_ok = "Defined Risk" not in (ts.options_level or "") and acct.margin_or_cash == "Margin"
            check(f"naked_options_allowed[{acct.account_number}]", naked_ok,
                  f"options_level='{ts.options_level}', margin_or_cash='{acct.margin_or_cash}'"
                  + ("" if naked_ok else "  ← selling naked puts/calls needs a Margin account with 'The Works'"))

        print("\n── 3. Market status & data ────────────────────────────────────")
        try:
            ms = await get_market_sessions(sess, [ExchangeType.NYSE])
            st = ms[0]
            check("market_sessions", True, f"NYSE state={st.state} open={st.open_at} close={st.close_at}")
        except Exception as e:
            check("market_sessions", False, repr(e)[:160])

        sym = args.sample
        try:
            eq = await get_market_data_by_type(sess, equities=[sym])
            px = eq[0].mark or eq[0].last or eq[0].close
            check("equity_quote", px is not None, f"{sym} mark/last={px} bid={eq[0].bid} ask={eq[0].ask}")
        except Exception as e:
            px = None
            check("equity_quote", False, repr(e)[:160])

        try:
            mm = await get_market_metrics(sess, [sym])
            m = mm[0]
            check("market_metrics", True,
                  f"{sym} IV30={m.implied_volatility_30_day} IVrank={m.implied_volatility_index_rank} "
                  f"liquidity_rating={m.liquidity_rating}")
        except Exception as e:
            check("market_metrics", False, repr(e)[:160])

        put_sym = None
        try:
            chain = (await NestedOptionChain.get(sess, sym))[0]
            exps = [e for e in chain.expirations if e.days_to_expiration >= 7]
            exp = min(exps, key=lambda e: abs(e.days_to_expiration - 30))
            if px is None:
                px = exp.strikes[len(exp.strikes) // 2].strike_price
            strike = min(exp.strikes, key=lambda s: abs(s.strike_price - Decimal(str(px))))
            put_sym, call_sym = strike.put, strike.call
            q = await get_market_data_by_type(sess, options=[put_sym, call_sym])
            qd = {x.symbol: x for x in q}
            p, cq = qd.get(put_sym), qd.get(call_sym)
            def mid(o):
                if o and o.bid is not None and o.ask is not None:
                    return (o.bid + o.ask) / 2
                return o.mark if o else None
            pm, cm = mid(p), mid(cq)
            detail = (f"{sym} exp={exp.expiration_date} ({exp.days_to_expiration} DTE) strike={strike.strike_price} "
                      f"put mid={pm} ({(float(pm)/float(px)*100 if pm else float('nan')):.2f}% of spot) "
                      f"call mid={cm} ({(float(cm)/float(px)*100 if cm else float('nan')):.2f}% of spot)")
            check("option_chain_and_quotes", pm is not None, detail)
            report["sample_option"] = {"symbol": sym, "spot": _d(px), "expiration": str(exp.expiration_date),
                                       "dte": exp.days_to_expiration, "strike": _d(strike.strike_price),
                                       "put_mid": _d(pm), "call_mid": _d(cm), "put_symbol": put_sym}
        except Exception as e:
            check("option_chain_and_quotes", False, repr(e)[:200])

        print("\n── 4. Dry-run: SELL 1 naked ATM put (no order is placed) ──────")
        if put_sym and accounts:
            acct = accounts[0]
            try:
                order = LimitOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    legs=[Leg(instrument_type=InstrumentType.EQUITY_OPTION, symbol=put_sym,
                              action=OrderAction.SELL_TO_OPEN, quantity=1)],
                    price=Decimal(str(report["sample_option"]["put_mid"] or 1)),  # credit
                )
                bpe = await acct.get_order_buying_power_effect(sess, order)
                notional = 100 * float(px)
                bp = float(bpe.change_in_buying_power)
                check("dry_run_naked_put", True,
                      f"BP effect={bp:,.0f} ({abs(bp)/notional*100:.1f}% of ${notional:,.0f} notional); "
                      f"isolated margin req={float(bpe.isolated_order_margin_requirement):,.0f}; "
                      f"current BP={float(bpe.current_buying_power):,.0f}")
                report["dry_run"] = {"put_symbol": put_sym, "change_in_buying_power": bp,
                                     "pct_of_notional": abs(bp) / notional * 100,
                                     "isolated_order_margin_requirement": _d(bpe.isolated_order_margin_requirement)}
            except Exception as e:
                check("dry_run_naked_put", False, repr(e)[:200])

    json.dump(report, open(REPORT, "w"), indent=1, default=str)
    print(f"\nReport written → {REPORT}")
    print("\n✔ PRE-FLIGHT PASSED" if ok else "\n✖ PRE-FLIGHT HAS FAILURES — see above")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", action="store_true", help="use api.cert.tastyworks.com")
    ap.add_argument("--sample", default="AAPL", help="sample underlying for chain + dry-run")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

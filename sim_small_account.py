#!/usr/bin/env python3
"""
Replay the sell-put backtest (history.csv) under real-account constraints.

What the original backtest ignores and this adds:
  • integer contracts (1 contract = 100 shares) priced with real monthly closes
  • a buying-power cap: Reg-T (25 % of notional, measured on tastytrade) or
    portfolio margin (~12 % of notional)
  • commissions ($1.10 / contract) and slippage (fraction of premium lost to spread)
  • dollar P&L compounding on real equity (the backtest sums % returns)
  • recovery sizing with the same rule as strategy.py, but capped by buying power

Usage:
  python3 sim_small_account.py                      # scenario table
  python3 sim_small_account.py --capital 50000 --margin 0.25 --bp-cap 0.5 --max-name-pct 0.25
"""
from __future__ import annotations
import argparse, math, sys
import numpy as np, pandas as pd

HIST = "history.csv"
PX_CACHE = "monthly_closes.csv"
COMMISSION = 1.10          # $/contract/month (open $1 + fees; expiry is free at tastytrade)


def load_prices(tickers: list[str]) -> pd.DataFrame:
    try:
        px = pd.read_csv(PX_CACHE, index_col=0, parse_dates=True)
        if set(tickers) <= set(px.columns):
            return px[tickers]
    except FileNotFoundError:
        pass
    import yfinance as yf
    raw = yf.download(tickers, start="2014-11-01", end="2025-01-05", interval="1mo",
                      auto_adjust=False, progress=False)
    px = raw["Close"]
    px.index = pd.to_datetime(px.index).to_period("M").to_timestamp()
    px.to_csv(PX_CACHE)
    return px


def simulate(hist: pd.DataFrame, px: pd.DataFrame, capital: float, margin: float,
             bp_cap: float, max_name_pct: float, recovery: bool = True,
             slippage: float = 0.10, unit_pct: float | None = None,
             recovery_mult: float = 2.0) -> dict:
    """
    capital       starting equity ($)
    margin        BP consumed per $ notional (0.25 Reg-T, ~0.12 PM)
    bp_cap        max fraction of equity usable as BP at any time
    max_name_pct  skip a name if ONE contract's notional exceeds this fraction of equity
    unit_pct      base size: notional per name as fraction of equity (None → 1 contract)
    recovery      apply the martingale rule (uniform multiplier) capped by bp_cap
    """
    equity = capital
    episode = 0.0                      # $ episode P&L (deficit when negative)
    rows = []
    months = sorted(hist.date.unique())
    for d in months:
        m = hist[(hist.date == d) & (hist.selling_side == "sell_put")]
        prev = d - pd.offsets.MonthBegin(1)
        act = []
        for _, r in m.iterrows():
            t = r.ticker
            if t not in px.columns or prev not in px.index:
                continue
            spot = px.at[prev, t]
            if not np.isfinite(spot) or spot <= 0:
                continue
            notional = 100 * spot
            if notional > max_name_pct * equity:
                continue
            base = 1 if unit_pct is None else int(unit_pct * equity // notional)
            if base < 1:
                continue
            act.append((t, spot, notional, base, r.prem_pct / 100, r.return_pct / 100))
        n_act = len(act)
        mult = 1
        if recovery and episode < 0 and n_act:
            base_prem = sum(b * n * p * (1 - slippage) for _, _, n, b, p, _ in act)
            if base_prem > 0:
                mult = max(1, math.ceil(-episode / base_prem)) * recovery_mult
        # cap by buying power
        base_bp = sum(b * n * margin for _, _, n, b, _, _ in act)
        bp_limit = bp_cap * equity
        if base_bp > 0:
            mult = min(mult, max(1, int(bp_limit // base_bp)))
        pnl = 0.0; notional_tot = 0.0; bp_used = 0.0; contracts = 0
        # if even 1× does not fit, drop the most expensive names until it fits
        act_sorted = sorted(act, key=lambda x: x[2])
        while act_sorted and sum(b * n * margin for _, _, n, b, _, _ in act_sorted) * mult > bp_limit:
            act_sorted.pop()
        for t, spot, notional, base, prem, ret in act_sorted:
            k = base * mult
            pnl += k * (notional * prem * (1 - slippage) + notional * min(ret, 0.0) - COMMISSION)
            notional_tot += k * notional; bp_used += k * notional * margin; contracts += k
        equity += pnl
        episode = min(0.0, episode + pnl)      # reset when deficit cleared
        rows.append(dict(date=d, equity=equity, pnl=pnl, names=len(act_sorted), eligible=n_act,
                         mult=mult, contracts=contracts, notional=notional_tot, bp_used=bp_used,
                         bp_pct=bp_used / max(equity - pnl, 1)))
        if equity <= 0:
            break
    df = pd.DataFrame(rows)
    eq = df.equity
    dd = (eq / eq.cummax() - 1).min()
    yrs = len(df) / 12
    cagr = (eq.iloc[-1] / capital) ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1.0
    return dict(final=eq.iloc[-1], cagr=cagr, maxdd=dd, worst_month=(df.pnl / (eq.shift(1).fillna(capital))).min(),
                names_p50=df.names.median(), names_min=df.names.min(), months_zero=(df.names == 0).sum(),
                bp_p50=df.bp_pct.median(), bp_p90=df.bp_pct.quantile(.9), bp_max=df.bp_pct.max(),
                mult_max=df.mult.max(), months_recov=(df.mult > 1).sum(), df=df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float); ap.add_argument("--margin", type=float, default=0.25)
    ap.add_argument("--bp-cap", type=float, default=0.5); ap.add_argument("--max-name-pct", type=float, default=0.25)
    ap.add_argument("--slippage", type=float, default=0.10); ap.add_argument("--no-recovery", action="store_true")
    ap.add_argument("--out", default="sim_small_account.csv")
    a = ap.parse_args()
    hist = pd.read_csv(HIST, parse_dates=["date"])
    tickers = sorted(hist.ticker.unique())
    px = load_prices(tickers)
    missing = [t for t in tickers if t not in px.columns or px[t].isna().all()]
    print(f"{len(tickers)} tickers in history, prices for {len(tickers) - len(missing)}; no prices (delisted): {missing}")

    if a.capital:
        r = simulate(hist, px, a.capital, a.margin, a.bp_cap, a.max_name_pct, not a.no_recovery, a.slippage)
        r["df"].to_csv(a.out, index=False)
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k != "df"})
        return

    scen = [
        # label, capital, margin, bp_cap, max_name_pct, recovery
        ("$50k  Reg-T  flat size, no recovery",         50_000, 0.25, 0.50, 0.25, False),
        ("$50k  Reg-T  recovery capped at 50% BP",      50_000, 0.25, 0.50, 0.25, True),
        ("$50k  Reg-T  recovery capped at 80% BP",      50_000, 0.25, 0.80, 0.25, True),
        ("$125k Reg-T  recovery capped at 50% BP",     125_000, 0.25, 0.50, 0.25, True),
        ("$125k PM     flat size, no recovery",        125_000, 0.12, 0.50, 0.25, False),
        ("$125k PM     recovery capped at 50% BP",     125_000, 0.12, 0.50, 0.25, True),
        ("$250k PM     recovery capped at 50% BP",     250_000, 0.12, 0.50, 0.25, True),
        ("$1M   PM     recovery capped at 50% BP",   1_000_000, 0.12, 0.50, 0.25, True),
        ("$1M   PM     recovery capped at 50% BP, 1%-unit", 1_000_000, 0.12, 0.50, 0.25, True),
    ]
    out = []
    for label, cap, mg, bpc, mnp, rec in scen:
        unit = 0.01 if "1%-unit" in label else None
        r = simulate(hist, px, cap, mg, bpc, mnp, rec, a.slippage, unit_pct=unit)
        out.append(dict(scenario=label, capital=cap, final=r["final"], cagr=r["cagr"], maxdd=r["maxdd"],
                        worst_month=r["worst_month"], names_p50=r["names_p50"], names_min=r["names_min"],
                        months_zero=r["months_zero"], bp_p50=r["bp_p50"], bp_p90=r["bp_p90"], bp_max=r["bp_max"],
                        mult_max=r["mult_max"], months_recov=r["months_recov"]))
    res = pd.DataFrame(out)
    pd.set_option("display.width", 250)
    print(res.to_string(index=False, formatters={
        "final": "${:,.0f}".format, "cagr": "{:.1%}".format, "maxdd": "{:.1%}".format, "worst_month": "{:.1%}".format,
        "bp_p50": "{:.0%}".format, "bp_p90": "{:.0%}".format, "bp_max": "{:.0%}".format}))
    res.to_csv(a.out, index=False)
    print(f"\nBacktest reference (no constraints, 100 names, 1 %-of-capital units): 120 % compounded over 2015-02..2024-12 "
          f"(≈ 8.3 % CAGR), max DD −18.7 %, notional up to 16× capital.")


if __name__ == "__main__":
    main()

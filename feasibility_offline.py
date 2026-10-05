#!/usr/bin/env python3
"""
Offline feasibility check (no broker login needed): can the backtested sizing
rule actually be traded with listed 100-share option contracts?

Backtest unit: 1 unit = 1 % of portfolio capital in NOTIONAL on one name.
Reality: the smallest tradable unit is ONE contract = 100 × spot.
So a name is tradable at size 1 only if 100 × spot ≤ capital / 100,
i.e. capital ≥ 10,000 × spot.

Also estimates Reg-T buying power for a naked ATM put (≈ 20 % of notional +
premium, min 10 %), and translates the backtest's uniform_size history into
buying-power needs.

Usage: python3 feasibility_offline.py [--capital 1000000] [--universe 2026.txt]
"""
from __future__ import annotations

import argparse
import re
import numpy as np
import pandas as pd
import yfinance as yf

REGT_ATM = 0.20          # Reg-T naked put: 20 % of underlying (ATM → no OTM credit)


def load_universe(path: str) -> list[str]:
    ts = [re.search(r"\(([^)]+)\)", l).group(1) for l in open(path) if re.search(r"\(([^)]+)\)", l)]
    return [t.replace(".", "-") for t in ts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1_000_000)
    ap.add_argument("--universe", default="2026.txt")
    ap.add_argument("--out", default="feasibility_offline.csv")
    a = ap.parse_args()

    tickers = load_universe(a.universe)
    px = yf.download(tickers, period="5d", interval="1d", auto_adjust=False, progress=False)["Close"]
    px = px.ffill().iloc[-1].dropna()
    missing = sorted(set(tickers) - set(px.index))

    unit = a.capital / 100
    df = pd.DataFrame({"spot": px.round(2)})
    df["contract_notional"]       = (df.spot * 100).round(0)
    df["min_capital_for_1_unit"]  = (df.spot * 10_000).round(0)
    df["contracts_at_size1"]      = np.floor(unit / df.contract_notional).astype(int)
    df["regT_bp_per_contract"]    = (df.contract_notional * REGT_ATM).round(0)
    df = df.sort_values("spot", ascending=False)
    df.to_csv(a.out)

    # backtest sizing → buying power
    port = pd.read_csv("portfolio_sell_put_1m.csv")
    bp_pct = port.capital_deployed * REGT_ATM * 100          # % of capital tied up as BP
    hist = pd.read_csv("history.csv", parse_dates=["date"])

    print(f"\nUniverse {a.universe}: {len(tickers)} names, prices for {len(px)}; missing: {missing}")
    print(f"Capital assumed: ${a.capital:,.0f}  →  1 unit (1 %) = ${unit:,.0f} notional per name")
    print(f"  names tradable at size 1 (≥1 contract fits in 1 unit): {(df.contracts_at_size1 >= 1).sum()} / {len(df)}")
    print(f"  names with ZERO contracts at size 1                   : {(df.contracts_at_size1 == 0).sum()}")
    print(f"  capital needed so EVERY name gets ≥1 contract at size 1: ${df.min_capital_for_1_unit.max():,.0f}  ({df.min_capital_for_1_unit.idxmax()})")
    print(f"  capital needed for the median name                     : ${df.min_capital_for_1_unit.median():,.0f}")
    print(f"  notional if 1 contract on every name                   : ${df.contract_notional.sum():,.0f}"
          f"  (Reg-T BP ≈ ${df.regT_bp_per_contract.sum():,.0f})")
    for cap in [250e3, 500e3, 1e6, 2e6, 5e6, 12e6]:
        n = (df.contract_notional <= cap / 100).sum()
        print(f"    ${cap/1e6:5.2f}M capital → {n:3d}/{len(df)} names tradable at size 1")

    print("\nBacktest sizing (sell_put_1m) translated to Reg-T buying power (20 % of notional):")
    print(f"  uniform_size > 1 in {(port.uniform_size > 1).sum()} of {len(port)} months; max uniform_size = {port.uniform_size.max()}")
    print(f"  notional deployed / capital: median {port.capital_deployed.median():.2f}x, p90 {port.capital_deployed.quantile(.9):.2f}x, "
          f"p99 {port.capital_deployed.quantile(.99):.2f}x, max {port.capital_deployed.max():.2f}x")
    print(f"  BP needed as % of capital  : median {bp_pct.median():.0f}%, p90 {bp_pct.quantile(.9):.0f}%, "
          f"p99 {bp_pct.quantile(.99):.0f}%, max {bp_pct.max():.0f}%  (>100% = NOT financeable)")
    print(f"  months where BP need > 100% of capital: {(bp_pct > 100).sum()}; > 50%: {(bp_pct > 50).sum()}")
    traded = hist[(hist.date >= "2022") & (hist.prem_pct > 0)]   # skip months carry prem_pct=0
    print(f"  backtest avg premium 2022-24 (traded months only): {traded.prem_pct.mean():.2f}% of spot per month (ATM, 30 DTE)")
    print(f"\nPer-name table → {a.out}")
    print(df.head(12).to_string())


if __name__ == "__main__":
    main()

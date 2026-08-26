#!/usr/bin/env python3
"""
Verify every number shown on the InsideSPX Momentum report page
(https://d7g7nkeytae81.cloudfront.net/strategies/ -> InsideSPX Momentum)
against this repository's simulation output.

The page presents the *uniform 1x sizing* variant of buy_call_1m
(no recovery scaling) plus a 4x premium-outlay variant, with free cash
earning the effective Fed Funds rate (FRED series FEDFUNDS).

Reconstruction, verified month-by-month against the page (119/119 rows):

  pnl_1x[m]  = sum over traded names of pnl_pu_pct / 100      (% of equity)
  capin[m]   = sum over traded names of call_prem_pct / 100   (% of equity)
  r_1x[m]    = pnl_1x[m] + FFR_mo[m] * (1 - capin[m]/100) * 100
  r_4x[m]    = 4*pnl_1x[m] + FFR_mo[m] * (1 - 4*capin[m]/100) * 100

Note: the 4x variant spends 4x the call premiums out of the same equity.
Nothing is borrowed (options embed the leverage), so no interest cost is
charged - the on-page label "3x borrowed at Fed Funds rate" is wrong,
the numbers are right for a 4x premium outlay.

Requires: pandas, numpy, and fedfunds.csv
(https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS&cosd=2015-01-01&coed=2025-01-01)
"""

import numpy as np
import pandas as pd

N_MONTHS = 119


def stats(r, rf_annual=0.0, compound=True):
    """Risk stats on a monthly return series (fractions)."""
    n = len(r)
    if compound:
        total = (1 + r).prod() - 1
        ann = (1 + r).prod() ** (12 / n) - 1
        cum = (1 + r).cumprod()
        peak = np.maximum.accumulate(cum)
        max_dd = ((cum - peak) / peak).min()
    else:
        total = r.sum()
        ann = r.mean() * 12
        cum = np.cumsum(r)
        peak = np.maximum.accumulate(cum)
        max_dd = (cum - peak).min()
    vol = r.std(ddof=1) * np.sqrt(12)
    sharpe = (ann - rf_annual) / vol
    down = r[r < rf_annual / 12]
    down_vol = np.std(down, ddof=1) * np.sqrt(12)
    var95 = np.percentile(r, 5)
    return {
        "total_pct": total * 100,
        "ann_pct": ann * 100,
        "vol_pct": vol * 100,
        "sharpe": sharpe,
        "sortino": (ann - rf_annual) / down_vol,
        "max_dd_pct": max_dd * 100,
        "calmar": ann / abs(max_dd),
        "var95_pct": var95 * 100,
        "cvar95_pct": r[r <= var95].mean() * 100,
        "win_pct": (r > 0).mean() * 100,
        "best_pct": r.max() * 100,
        "worst_pct": r.min() * 100,
    }


def show(label, s, page):
    print(f"\n── {label} " + "─" * (58 - len(label)))
    keys = ["total_pct", "ann_pct", "vol_pct", "sharpe", "sortino",
            "max_dd_pct", "calmar", "win_pct", "best_pct", "worst_pct",
            "var95_pct", "cvar95_pct"]
    names = ["Total return", "Ann. return", "Ann. vol", "Sharpe", "Sortino",
             "Max drawdown", "Calmar", "Win rate", "Best month", "Worst month",
             "VaR 95%", "CVaR 95%"]
    for k, nm in zip(keys, names):
        pg = page.get(k)
        pg_s = f"{pg:>8.2f}" if pg is not None else "       –"
        flag = ""
        if pg is not None:
            flag = "  OK" if abs(s[k] - pg) <= 0.06 * max(1, abs(pg)) else "  ** MISMATCH **"
        print(f"  {nm:<14} computed {s[k]:>9.2f}   page {pg_s}{flag}")


def main():
    h = pd.read_csv("history_buy_call_1m.csv", parse_dates=["date"])
    ff = pd.read_csv("fedfunds.csv", parse_dates=["observation_date"])
    ff["ym"] = ff["observation_date"].dt.strftime("%Y-%m")
    ffr_mo = ff.set_index("ym")["FEDFUNDS"] / 100 / 12

    h["ym"] = h["date"].dt.strftime("%Y-%m")
    tr = h[h["side"] == "buy_call"]
    g = tr.groupby("ym")
    pnl_1x = g["pnl_pu_pct"].sum() / 100      # % of equity
    capin = g["call_prem_pct"].sum() / 100    # % of equity
    bets = g.size()

    assert len(pnl_1x) == N_MONTHS

    f = ffr_mo.reindex(pnl_1x.index)
    r1 = (pnl_1x / 100 + f * (1 - capin / 100)).values
    r4 = (4 * pnl_1x / 100 + f * (1 - 4 * capin / 100)).values

    avg_ffr = ff[ff["ym"].isin(pnl_1x.index)]["FEDFUNDS"].mean()

    # Values shown on the live page (strategies index, InsideSPX section)
    page_1x = {"total_pct": 103.9, "ann_pct": 7.5, "vol_pct": 4.5,
               "sharpe": 1.65, "sortino": 3.12, "max_dd_pct": -7.3,
               "calmar": 1.02, "win_pct": 68.9, "best_pct": 4.4,
               "worst_pct": -2.2, "var95_pct": -1.6, "cvar95_pct": -2.0}
    page_4x = {"total_pct": 792.5, "ann_pct": 24.7, "vol_pct": 18.0,
               "sharpe": 1.38, "sortino": 2.57, "max_dd_pct": -28.7,
               "calmar": 0.86, "win_pct": 68.9, "best_pct": 17.2,
               "worst_pct": -8.8, "var95_pct": -7.5, "cvar95_pct": -8.4}

    s1 = stats(r1, rf_annual=0.0)
    s4 = stats(r4, rf_annual=0.0)
    show("1x sizing, cash at FFR (compound, 0% RF)", s1, page_1x)
    show("4x premium outlay, cash at FFR (compound, 0% RF)", s4, page_4x)

    print(f"\n  Avg capital in options: 1x {capin.mean():.2f}%   4x {4*capin.mean():.2f}%")
    print(f"  Bets per month: min {bets.min()}  median {int(bets.median())}  max {bets.max()}")
    print(f"  Avg FFR over window: {avg_ffr:.2f}%")
    print(f"  Sharpe vs FFR instead of 0%: "
          f"1x {(s1['ann_pct']-avg_ffr)/s1['vol_pct']:.2f}   "
          f"4x {(s4['ann_pct']-avg_ffr)/s4['vol_pct']:.2f}")

    # 4x if 3x really were borrowed at FFR (what the current label claims)
    r4b = (4 * pnl_1x / 100 + f * (1 - 4 * capin / 100) - 3 * f).values
    s4b = stats(r4b, rf_annual=0.0)
    print(f"\n  If 3x were truly borrowed at FFR, 4x would be: "
          f"total {s4b['total_pct']:.1f}%  ann {s4b['ann_pct']:.1f}%  "
          f"sharpe {s4b['sharpe']:.2f}  maxDD {s4b['max_dd_pct']:.1f}%")

    # Old recovery-sizing variant (previous page revision), both conventions
    p = pd.read_csv("portfolio_buy_call_1m.csv")
    rr = p["monthly_return_pct"].values / 100
    sa = stats(rr, rf_annual=0.04, compound=False)
    sc = stats(rr, rf_annual=0.04, compound=True)
    print("\n── legacy 2x-recovery variant (portfolio_buy_call_1m.csv) ──")
    print(f"  fixed-capital (strategy.py convention): total {sa['total_pct']:.1f}%  "
          f"ann {sa['ann_pct']:.1f}%  sharpe {sa['sharpe']:.2f}  "
          f"maxDD {sa['max_dd_pct']:.1f}pts  calmar {sa['calmar']:.2f}")
    print(f"  compounded   (plot_results.py convention): total {sc['total_pct']:.1f}%  "
          f"ann {sc['ann_pct']:.1f}%  sharpe {sc['sharpe']:.2f}  "
          f"maxDD {sc['max_dd_pct']:.1f}%  calmar {sc['calmar']:.2f}")
    print("  (the old page mixed these: +351.3% total from the fixed-capital "
          "cumulation next to 32.8%/0.63/-19.9% from the compounded one)")


if __name__ == "__main__":
    main()

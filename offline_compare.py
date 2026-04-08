#!/usr/bin/env python3
"""
Offline strategy comparison using cached data from history.csv + stock_*.csv files.

Reads premiums/returns from previously-generated CSVs and simulates all three
momentum filters without needing AWS credentials.

DTE scaling applied at load time: prem_scaled = prem_raw × (1 + 0.4 × (30/25 − 1))
(same as strategy.py with TARGET_DTE=30, ASSUMED_DTE=25)
"""

import numpy as np
import pandas as pd
from glob import glob

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_SIZE      = 5_000
FALLBACK_PREM = 0.03     # fraction
DTE_SCALE     = 1 + 0.4 * (30 / 25 - 1)   # = 1.08  (no DTE column in old CSVs)


# ── Load data ──────────────────────────────────────────────────────────────────

def load_stock_data() -> dict[str, pd.DataFrame]:
    """
    Load per-stock monthly data from the individual stock_*.csv files.
    Returns {ticker: DataFrame(date, return_pct, prem_pct)} sorted by date.
    """
    data = {}
    for path in sorted(glob("stock_*.csv")):
        ticker = path.removeprefix("stock_").removesuffix(".csv")
        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        # Apply DTE scaling (old CSVs used raw premiums without scaling)
        df["prem_pct"] = df["prem_pct"] * DTE_SCALE
        data[ticker] = df
    print(f"Loaded {len(data)} tickers from stock_*.csv files")
    return data


# ── Strategy simulation ────────────────────────────────────────────────────────

def simulate(
    stock_data: dict[str, pd.DataFrame],
    signal: str,            # 'none' | '1m' | '6m'
) -> pd.DataFrame:
    """
    Portfolio-level uniform recovery sizing across all active stocks.

    signal:
      'none' — sell PUT every month (no filter)
      '1m'   — sell PUT only when previous 1m return was positive
      '6m'   — sell PUT only when 6m cumulative return > 0

    Returns monthly portfolio DataFrame.
    """
    # Build matrix: date × ticker → (return_pct, prem_pct)
    all_dates = sorted({
        row["date"]
        for df in stock_data.values()
        for _, row in df.iterrows()
    })

    # Pre-build dicts for fast lookup
    returns: dict[str, dict] = {}   # ticker → {date: return_pct}
    prems:   dict[str, dict] = {}   # ticker → {date: prem_pct}
    for ticker, df in stock_data.items():
        returns[ticker] = dict(zip(df["date"], df["return_pct"] / 100.0))
        prems[ticker]   = dict(zip(df["date"], df["prem_pct"]   / 100.0))

    # Per-ticker state for momentum signals
    last_ret:  dict[str, float] = {t: 0.0  for t in stock_data}  # prev 1m return
    prices_6m: dict[str, list]  = {t: []   for t in stock_data}  # rolling 6 prices

    portfolio_episode_pnl = 0.0
    portfolio_cum_pnl     = 0.0
    monthly_rows = []

    for date in all_dates:
        portfolio_cumulated_loss = max(0.0, -portfolio_episode_pnl)
        in_recovery              = portfolio_cumulated_loss > 0.0

        # Determine which stocks trade this month
        active = []
        for ticker in stock_data:
            if date not in returns[ticker]:
                continue

            r = returns[ticker][date]

            if signal == "1m":
                trade = (last_ret[ticker] >= 0.0)
            elif signal == "6m":
                hist = prices_6m[ticker]
                trade = (hist[-1] >= hist[-6]) if len(hist) >= 6 else True
            else:   # 'none'
                trade = True

            if trade:
                active.append(ticker)

        n_active = len(active)

        # Uniform recovery size
        if in_recovery and n_active > 0:
            avg_prem = float(np.mean([
                prems[ticker].get(date, FALLBACK_PREM) for ticker in active
            ]))
            denom = avg_prem if avg_prem > 0 else FALLBACK_PREM
            uniform_size = min(MAX_SIZE, max(1, int(np.ceil(
                portfolio_cumulated_loss / (n_active * denom / 100.0)
            ))))
        else:
            uniform_size = 1

        # Compute month PnL
        month_portfolio_pnl = 0.0
        for ticker in stock_data:
            if date not in returns[ticker]:
                continue
            r    = returns[ticker][date]
            prem = prems[ticker].get(date, FALLBACK_PREM)
            if ticker in active:
                pnl_pu = prem + min(r, 0.0)
                month_portfolio_pnl += uniform_size * pnl_pu / 100.0

        # Update state
        portfolio_episode_pnl += month_portfolio_pnl
        portfolio_cum_pnl     += month_portfolio_pnl
        if portfolio_episode_pnl >= 0.0:
            portfolio_episode_pnl = 0.0

        monthly_rows.append({
            "date":                         date,
            "monthly_return_pct":           round(month_portfolio_pnl * 100, 4),
            "cumulative_return_pct":        round(portfolio_cum_pnl   * 100, 4),
            "capital_deployed":             round(uniform_size * n_active / 100.0, 2),
            "num_stocks_trading":           n_active,
            "uniform_size":                 uniform_size,
            "portfolio_cumulated_loss_pct": round(portfolio_cumulated_loss * 100, 4),
        })

        # Update momentum state AFTER computing pnl (use this month's return)
        for ticker in stock_data:
            if date in returns[ticker]:
                r = returns[ticker][date]
                last_ret[ticker] = r
                # Prices: track cumulative product index (start at 1.0)
                prev_price = prices_6m[ticker][-1] if prices_6m[ticker] else 1.0
                prices_6m[ticker].append(prev_price * (1 + r))

    return pd.DataFrame(monthly_rows)


# ── Risk statistics ────────────────────────────────────────────────────────────

def compute_risk_stats(portfolio_df: pd.DataFrame, rf_annual: float = 0.04) -> dict:
    mr = portfolio_df["monthly_return_pct"].values / 100.0
    n  = len(mr)
    mean_mo  = np.mean(mr)
    std_mo   = np.std(mr, ddof=1) if n > 1 else 0.0
    ann_ret  = mean_mo * 12
    ann_vol  = std_mo  * np.sqrt(12)
    rf_mo    = rf_annual / 12

    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0.0

    down     = mr[mr < rf_mo]
    down_vol = np.std(down, ddof=1) * np.sqrt(12) if len(down) > 1 else 0.0
    sortino  = (ann_ret - rf_annual) / down_vol if down_vol > 0 else 0.0

    cum  = np.cumsum(mr)
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    var95  = float(np.percentile(mr, 5))
    var99  = float(np.percentile(mr, 1))
    tail95 = mr[mr <= var95]
    cvar95 = float(tail95.mean()) if len(tail95) > 0 else var95

    win_rate = float((mr > 0).mean() * 100)

    return {
        "n_months":         n,
        "ann_return_pct":   round(ann_ret  * 100, 2),
        "ann_vol_pct":      round(ann_vol  * 100, 2),
        "sharpe_4pct_rf":   round(sharpe,         3),
        "sortino_4pct_rf":  round(sortino,         3),
        "max_drawdown_pct": round(max_dd   * 100, 2),
        "calmar":           round(calmar,          3),
        "var_95_pct":       round(var95    * 100, 2),
        "var_99_pct":       round(var99    * 100, 2),
        "cvar_95_pct":      round(cvar95   * 100, 2),
        "win_rate_pct":     round(win_rate,        1),
        "best_month_pct":   round(float(mr.max()) * 100, 2),
        "worst_month_pct":  round(float(mr.min()) * 100, 2),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    stock_data = load_stock_data()

    configs = [
        ("no_filter", "none", "No momentum filter (always sell PUT)"),
        ("mom_1m",    "1m",   "1M momentum: sell PUT if prev month UP"),
        ("mom_6m",    "6m",   "6M momentum: sell PUT if 6m return > 0"),
    ]

    results = {}
    for key, sig, label in configs:
        print(f"\nSimulating: {label} …")
        pf = simulate(stock_data, signal=sig)
        risk = compute_risk_stats(pf)
        results[key] = (label, pf, risk)
        pf.to_csv(f"portfolio_{key}.csv", index=False)
        print(f"  → Ann return: {risk['ann_return_pct']:.2f}%  "
              f"Sharpe: {risk['sharpe_4pct_rf']:.3f}  "
              f"MaxDD: {risk['max_drawdown_pct']:.2f}%")

    # ── Comparison table ──────────────────────────────────────────────────────
    print("\n" + "=" * 105)
    print("  STRATEGY COMPARISON  (offline, cached premiums + DTE scaling ×1.08)")
    print(f"  Universe: {len(stock_data)} stocks  |  Period: 2015-01 → 2024-12")
    print("=" * 105)

    header = (
        f"{'Strategy':<40}"
        f"{'AnnRet%':>8}{'AnnVol%':>8}{'Sharpe':>8}{'Sortino':>8}"
        f"{'MaxDD%':>8}{'Calmar':>8}{'Win%':>7}"
        f"{'Best%':>8}{'Worst%':>8}"
    )
    print(header)
    print("-" * len(header))

    for key, sig, label in configs:
        label, _, risk = results[key]
        row = (
            f"{label:<40}"
            f"{risk['ann_return_pct']:>8.2f}"
            f"{risk['ann_vol_pct']:>8.2f}"
            f"{risk['sharpe_4pct_rf']:>8.3f}"
            f"{risk['sortino_4pct_rf']:>8.3f}"
            f"{risk['max_drawdown_pct']:>8.2f}"
            f"{risk['calmar']:>8.3f}"
            f"{risk['win_rate_pct']:>7.1f}"
            f"{risk['best_month_pct']:>8.2f}"
            f"{risk['worst_month_pct']:>8.2f}"
        )
        print(row)

    print("=" * 105)
    print("\nPer-strategy detailed stats:")
    for key, sig, label in configs:
        label, pf, risk = results[key]
        print(f"\n  [{label}]")
        print(f"    Ann return   : {risk['ann_return_pct']:>8.2f} %")
        print(f"    Ann vol      : {risk['ann_vol_pct']:>8.2f} %")
        print(f"    Sharpe       : {risk['sharpe_4pct_rf']:>8.3f}")
        print(f"    Sortino      : {risk['sortino_4pct_rf']:>8.3f}")
        print(f"    Max drawdown : {risk['max_drawdown_pct']:>8.2f} %")
        print(f"    Calmar       : {risk['calmar']:>8.3f}")
        print(f"    VaR 95%      : {risk['var_95_pct']:>8.2f} %")
        print(f"    CVaR 95%     : {risk['cvar_95_pct']:>8.2f} %")
        print(f"    Win rate     : {risk['win_rate_pct']:>8.1f} %")
        print(f"    Best month   : {risk['best_month_pct']:>8.2f} %")
        print(f"    Worst month  : {risk['worst_month_pct']:>8.2f} %")
        max_dep = pf["capital_deployed"].max()
        max_sz  = pf["uniform_size"].max()
        print(f"    Max cap dep  : {max_dep:>8.2f}x")
        print(f"    Max unif sz  : {max_sz:>8}")

    print()
    print("Note: 'No filter' and '6M filter' CSVs saved to portfolio_no_filter.csv / portfolio_mom_6m.csv")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
SPX Single Equity Vol Selling Strategy Simulator
=================================================

Strategy rules:
  1. Universe  : 100 biggest SPX single equities
  2. Timeframe : monthly candles
  3. Month 0   : sell ATM put (size=1) + ATM call (size=1)
  4. Each subsequent month, after observing the last candle:
       UP  candle → size up PUTS  for recovery, CALL  stays size=1
       DOWN candle → size up CALLS for recovery, PUT   stays size=1
  5. Recovery sizing:
       recovery_size = ceil( |accumulated_pnl_loss| / PREMIUM )
       where PREMIUM = 3 % of stock price per unit per month
  6. Reset both sides to size=1 after cumulative PnL turns positive again.

PnL model (simplified, per unit, in % of stock price):
  put_pnl_pct  = PREMIUM + min(r, 0)   →  capped at PREMIUM, unbounded below
  call_pnl_pct = PREMIUM - max(r, 0)   →  capped at PREMIUM, unbounded below
  where r = monthly return of the stock
"""

import sys
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────────
PREMIUM      = 0.03          # 3 % flat premium per unit per month
START_DATE   = "2015-01-01"
END_DATE     = "2024-12-31"
TOP_N        = 100
MAX_SIZE     = 5_000         # safety cap on position size (units)

# Top-100 S&P 500 names by approximate market cap (2024)
TOP100_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B",
    "LLY",  "AVGO", "JPM",  "TSLA", "UNH",  "V",     "XOM",  "MA",
    "JNJ",  "PG",   "COST", "HD",   "MRK",  "ABBV",  "CVX",  "CRM",
    "WMT",  "BAC",  "NFLX", "AMD",  "ORCL", "KO",    "PEP",  "ACN",
    "LIN",  "ADBE", "TMO",  "MCD",  "CSCO", "ABT",   "GE",   "CAT",
    "IBM",  "INTU", "PM",   "WFC",  "GS",   "AXP",   "AMGN", "DHR",
    "ISRG", "TXN",  "SPGI", "BKNG", "SYK",  "BLK",   "UNP",  "RTX",
    "NOW",  "NEE",  "HON",  "VRTX", "MS",   "LOW",   "AMAT", "C",
    "PLD",  "LRCX", "ADP",  "T",    "BMY",  "ETN",   "PANW", "SCHW",
    "BSX",  "MU",   "DE",   "GILD", "ELV",  "ADI",   "MMC",  "CB",
    "SO",   "MDLZ", "ZTS",  "REGN", "BA",   "PGR",   "DUK",  "CI",
    "SHW",  "CME",  "MCO",  "CEG",  "TJX",  "KLAC",  "EMR",  "APH",
    "FI",   "PYPL", "ITW",  "ECL",
]

# ── Data Fetching ──────────────────────────────────────────────────────────────

def fetch_monthly_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download adjusted monthly close prices for all tickers at once."""
    print(f"Downloading monthly price data for {len(tickers)} tickers …")
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        interval="1mo",
        auto_adjust=True,
        progress=False,
    )
    # Keep only Close prices
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})

    # Drop tickers with too few data points (< 24 months)
    closes = closes.dropna(axis=1, thresh=24)
    print(f"  → {closes.shape[1]} tickers retained after data quality filter")
    return closes


# ── Strategy Simulation ────────────────────────────────────────────────────────

def simulate_stock(ticker: str, prices: pd.Series) -> pd.DataFrame:
    """
    Simulate the vol-selling strategy for a single stock.

    Returns a DataFrame with one row per month containing:
      date, return, put_size, call_size, put_pnl_pct, call_pnl_pct,
      month_pnl_pct, cumulative_pnl_pct, recovery_mode, max_size_hit
    """
    prices = prices.dropna()
    if len(prices) < 3:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    n       = len(returns)

    records    = []
    cum_pnl    = 0.0   # cumulative PnL in % of stock price (per unit basis)
    put_size   = 1
    call_size  = 1
    recovery   = False
    first_month = True

    for i in range(n):
        r    = float(returns.iloc[i])
        date = returns.index[i]

        # ── Realise PnL for month i using sizes set at end of month i-1 ──────
        put_pnl  = put_size  * (PREMIUM + min(r, 0.0))   # profit when stock flat/up
        call_pnl = call_size * (PREMIUM - max(r, 0.0))   # profit when stock flat/down
        month_pnl = put_pnl + call_pnl
        cum_pnl  += month_pnl

        # Track whether we hit the safety cap this month
        max_hit = (put_size >= MAX_SIZE or call_size >= MAX_SIZE)

        records.append({
            "date":             date,
            "return_pct":       round(r * 100, 4),
            "put_size":         put_size,
            "call_size":        call_size,
            "put_pnl_pct":      round(put_pnl  * 100, 4),
            "call_pnl_pct":     round(call_pnl * 100, 4),
            "month_pnl_pct":    round(month_pnl * 100, 4),
            "cumulative_pnl_pct": round(cum_pnl * 100, 4),
            "recovery_mode":    recovery,
            "max_size_hit":     max_hit,
        })

        # ── Decide sizes for NEXT month ───────────────────────────────────────
        if cum_pnl >= 0.0 and not first_month:
            # Full recovery (or still in profit): reset to base
            recovery  = False
            put_size  = 1
            call_size = 1
        else:
            if cum_pnl < 0.0:
                recovery = True

            # Recovery size = units needed so premium covers accumulated loss
            if recovery:
                rec_size = int(np.ceil(abs(cum_pnl) / PREMIUM))
                rec_size = max(1, min(rec_size, MAX_SIZE))
            else:
                rec_size = 1

            if r >= 0.0:
                # UP candle → size up PUTS; call stays at 1
                put_size  = rec_size
                call_size = 1
            else:
                # DOWN candle → size up CALLS; put stays at 1
                call_size = rec_size
                put_size  = 1

        first_month = False

    return pd.DataFrame(records)


# ── Portfolio Aggregation ──────────────────────────────────────────────────────

def run_portfolio(closes: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Simulate strategy for every ticker; aggregate equally-weighted portfolio PnL.
    """
    stock_results: dict[str, pd.DataFrame] = {}

    for ticker in closes.columns:
        df = simulate_stock(ticker, closes[ticker])
        if not df.empty:
            stock_results[ticker] = df

    if not stock_results:
        raise RuntimeError("No valid stock simulations produced.")

    # Build equal-weight portfolio monthly PnL (average across stocks each month)
    monthly_pnl_list = []
    for ticker, df in stock_results.items():
        s = df.set_index("date")["month_pnl_pct"].rename(ticker)
        monthly_pnl_list.append(s)

    pnl_wide    = pd.concat(monthly_pnl_list, axis=1)
    port_monthly = pnl_wide.mean(axis=1).rename("portfolio_month_pnl_pct")
    port_cumul   = port_monthly.cumsum().rename("portfolio_cum_pnl_pct")
    portfolio_df = pd.concat([port_monthly, port_cumul], axis=1).reset_index()

    return stock_results, portfolio_df


# ── Summary Statistics ─────────────────────────────────────────────────────────

def compute_summary(stock_results: dict[str, pd.DataFrame], portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-stock and portfolio summary statistics."""
    rows = []
    for ticker, df in stock_results.items():
        total_months  = len(df)
        total_pnl     = df["month_pnl_pct"].sum()
        avg_monthly   = df["month_pnl_pct"].mean()
        win_rate      = (df["month_pnl_pct"] > 0).mean() * 100
        max_drawdown  = (df["cumulative_pnl_pct"] - df["cumulative_pnl_pct"].cummax()).min()
        max_put_size  = df["put_size"].max()
        max_call_size = df["call_size"].max()
        max_hit       = df["max_size_hit"].any()
        recovery_pct  = df["recovery_mode"].mean() * 100
        final_cum_pnl = df["cumulative_pnl_pct"].iloc[-1]

        rows.append({
            "ticker":             ticker,
            "months":             total_months,
            "total_pnl_pct":      round(total_pnl,     2),
            "final_cum_pnl_pct":  round(final_cum_pnl, 2),
            "avg_monthly_pnl_pct":round(avg_monthly,   4),
            "win_rate_pct":       round(win_rate,       1),
            "max_drawdown_pct":   round(max_drawdown,   2),
            "max_put_size":       int(max_put_size),
            "max_call_size":      int(max_call_size),
            "max_size_hit":       max_hit,
            "pct_months_recovery":round(recovery_pct,  1),
        })

    summary = pd.DataFrame(rows).sort_values("total_pnl_pct", ascending=False)

    # Add portfolio row
    port_row = {
        "ticker":             "PORTFOLIO (equal-weight)",
        "months":             len(portfolio_df),
        "total_pnl_pct":      round(portfolio_df["portfolio_month_pnl_pct"].sum(), 2),
        "final_cum_pnl_pct":  round(portfolio_df["portfolio_cum_pnl_pct"].iloc[-1], 2),
        "avg_monthly_pnl_pct":round(portfolio_df["portfolio_month_pnl_pct"].mean(), 4),
        "win_rate_pct":       round((portfolio_df["portfolio_month_pnl_pct"] > 0).mean() * 100, 1),
        "max_drawdown_pct":   round(
            (portfolio_df["portfolio_cum_pnl_pct"] -
             portfolio_df["portfolio_cum_pnl_pct"].cummax()).min(), 2),
        "max_put_size":       "–",
        "max_call_size":      "–",
        "max_size_hit":       "–",
        "pct_months_recovery":"–",
    }
    summary = pd.concat([pd.DataFrame([port_row]), summary], ignore_index=True)

    return summary


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_summary(summary: pd.DataFrame) -> None:
    port = summary.iloc[0]
    print("\n" + "=" * 72)
    print("  SPX SINGLE-EQUITY VOL SELLING STRATEGY  —  SIMULATION RESULTS")
    print("=" * 72)
    print(f"  Premium assumption : {PREMIUM*100:.1f}% per month per unit (ATM options)")
    print(f"  Backtest period    : {START_DATE}  →  {END_DATE}")
    print(f"  Universe           : top {TOP_N} SPX single equities")
    print(f"  Sizing rule        : UP candle → bigger PUT size | DOWN → bigger CALL")
    print(f"  Recovery reset     : when cumulative PnL turns ≥ 0")
    print("=" * 72)
    print(f"\n{'PORTFOLIO (equal-weight avg across stocks)':}")
    print(f"  Total PnL          : {port['total_pnl_pct']:>8.2f} %")
    print(f"  Final Cum PnL      : {port['final_cum_pnl_pct']:>8.2f} %")
    print(f"  Avg monthly PnL    : {port['avg_monthly_pnl_pct']:>8.4f} %")
    print(f"  Win rate           : {port['win_rate_pct']:>8.1f} %")
    print(f"  Max drawdown       : {port['max_drawdown_pct']:>8.2f} %")
    print()
    print(f"{'TOP 10 STOCKS (by total PnL)':}")
    top10 = summary[summary["ticker"] != "PORTFOLIO (equal-weight)"].head(10)
    print(
        top10[[
            "ticker", "total_pnl_pct", "avg_monthly_pnl_pct",
            "win_rate_pct", "max_drawdown_pct",
            "max_put_size", "max_call_size", "pct_months_recovery",
        ]].to_string(index=False)
    )
    print()
    print(f"{'BOTTOM 10 STOCKS (by total PnL)':}")
    bot10 = summary[summary["ticker"] != "PORTFOLIO (equal-weight)"].tail(10)
    print(
        bot10[[
            "ticker", "total_pnl_pct", "avg_monthly_pnl_pct",
            "win_rate_pct", "max_drawdown_pct",
            "max_put_size", "max_call_size", "pct_months_recovery",
        ]].to_string(index=False)
    )

    # Stocks that hit the max-size cap
    capped = summary[summary["max_size_hit"] == True]
    if not capped.empty:
        print(f"\n⚠  {len(capped)} stock(s) hit the MAX_SIZE={MAX_SIZE} cap:")
        print("  " + ", ".join(capped["ticker"].tolist()))
    print("=" * 72)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    tickers = TOP100_TICKERS[:TOP_N]

    # 1. Fetch data
    closes = fetch_monthly_prices(tickers, START_DATE, END_DATE)

    # 2. Simulate per stock + aggregate portfolio
    print("Running strategy simulation …")
    stock_results, portfolio_df = run_portfolio(closes)
    print(f"  → Simulated {len(stock_results)} stocks")

    # 3. Summary statistics
    summary = compute_summary(stock_results, portfolio_df)

    # 4. Print report
    print_summary(summary)

    # 5. Save outputs
    summary.to_csv("summary.csv", index=False)
    portfolio_df.to_csv("portfolio_pnl.csv", index=False)

    # Save per-stock detailed logs
    for ticker, df in stock_results.items():
        safe = ticker.replace("-", "_")
        df.to_csv(f"stock_{safe}.csv", index=False)

    print(f"\nOutputs written:")
    print("  summary.csv        — per-stock + portfolio summary statistics")
    print("  portfolio_pnl.csv  — monthly portfolio PnL time series")
    print("  stock_<TICKER>.csv — detailed monthly trade log per stock")


if __name__ == "__main__":
    main()

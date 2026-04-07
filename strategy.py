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
  5. Recovery sizing — KEY RULE:
       Losses are counted PER SIDE only.  The winning side keeps its
       premium intact and does NOT reduce the losing side's loss.
       Example: -10 % candle → call earns +3 % (intact),
                                put  loses  7 % (= 3 % - 10 %)
       → need ceil(7 % / 3 %) = 3 units of CALL next month to recover.

       put_gross_loss  accumulates whenever put goes ITM (r < -PREMIUM)
       call_gross_loss accumulates whenever call goes ITM (r >  PREMIUM)

       call_size_next = ceil(put_gross_loss  / PREMIUM)   after DOWN candle
       put_size_next  = ceil(call_gross_loss / PREMIUM)   after UP   candle

  6. Reset both sides to size=1 when cumulative total PnL turns >= 0.

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

def _next_sizes(
    r: float,
    cum_pnl: float,
    put_gross_loss: float,
    call_gross_loss: float,
    first_month: bool,
) -> tuple[int, int, bool]:
    """
    Compute (put_size, call_size, recovery_mode) for the NEXT month.

    Sizing rule:
      UP  candle → put_size = ceil(call_gross_loss / PREMIUM), call_size = 1
      DOWN candle → call_size = ceil(put_gross_loss  / PREMIUM), put_size = 1
    Reset to (1, 1) when cumulative total PnL >= 0.
    """
    if cum_pnl >= 0.0 and not first_month:
        return 1, 1, False

    if r >= 0.0:   # UP candle → size up PUTS
        rec = max(1, int(np.ceil(call_gross_loss / PREMIUM)))
        rec = min(rec, MAX_SIZE)
        return rec, 1, cum_pnl < 0.0
    else:          # DOWN candle → size up CALLS
        rec = max(1, int(np.ceil(put_gross_loss / PREMIUM)))
        rec = min(rec, MAX_SIZE)
        return 1, rec, cum_pnl < 0.0


def simulate_stock(ticker: str, prices: pd.Series) -> pd.DataFrame:
    """
    Simulate the vol-selling strategy for a single stock.

    Returns a DataFrame with one row per month containing:
      date, return, put_size, call_size, put_pnl_pct, call_pnl_pct,
      month_pnl_pct, cumulative_pnl_pct, recovery_mode,
      put_gross_loss_pct, call_gross_loss_pct, max_size_hit
    """
    prices = prices.dropna()
    if len(prices) < 3:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    n       = len(returns)

    records        = []
    cum_pnl        = 0.0
    put_gross_loss = 0.0   # accumulated gross loss from PUT going ITM
    call_gross_loss= 0.0   # accumulated gross loss from CALL going ITM
    put_size       = 1
    call_size      = 1
    recovery       = False
    first_month    = True

    for i in range(n):
        r    = float(returns.iloc[i])
        date = returns.index[i]

        # ── PnL for this month (sizes were set at end of previous month) ──────
        put_pnl_pu  = PREMIUM + min(r, 0.0)          # per-unit put PnL
        call_pnl_pu = PREMIUM - max(r, 0.0)          # per-unit call PnL
        put_pnl     = put_size  * put_pnl_pu
        call_pnl    = call_size * call_pnl_pu
        month_pnl   = put_pnl + call_pnl
        cum_pnl    += month_pnl

        # ── Accumulate GROSS losses per side (used for sizing, not reset) ─────
        # Only add when the side is actually ITM (pnl per unit < 0)
        if put_pnl_pu < 0.0:
            put_gross_loss  += put_size  * abs(put_pnl_pu)
        if call_pnl_pu < 0.0:
            call_gross_loss += call_size * abs(call_pnl_pu)

        max_hit = (put_size >= MAX_SIZE or call_size >= MAX_SIZE)

        records.append({
            "date":                date,
            "return_pct":          round(r * 100, 4),
            "put_size":            put_size,
            "call_size":           call_size,
            "put_pnl_pct":         round(put_pnl       * 100, 4),
            "call_pnl_pct":        round(call_pnl      * 100, 4),
            "month_pnl_pct":       round(month_pnl     * 100, 4),
            "cumulative_pnl_pct":  round(cum_pnl       * 100, 4),
            "put_gross_loss_pct":  round(put_gross_loss * 100, 4),
            "call_gross_loss_pct": round(call_gross_loss* 100, 4),
            "recovery_mode":       recovery,
            "max_size_hit":        max_hit,
        })

        # ── Decide sizes for NEXT month ───────────────────────────────────────
        put_size, call_size, recovery = _next_sizes(
            r, cum_pnl, put_gross_loss, call_gross_loss, first_month
        )

        # If fully recovered, clear the gross-loss accumulators for fresh start
        if not recovery:
            put_gross_loss  = 0.0
            call_gross_loss = 0.0

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


# ── Single-Stock Trace ─────────────────────────────────────────────────────────

def trace_stock(ticker: str) -> None:
    """
    Fetch data for one ticker and print a month-by-month sizing walk-through,
    showing exactly how position sizes are determined from the previous candle.
    """
    print(f"\n{'='*80}")
    print(f"  STEP-BY-STEP SIZING TRACE — {ticker}")
    print(f"  Premium = {PREMIUM*100:.1f}% per unit per month")
    print(f"{'='*80}")
    print(
        f"\n{'Month':<10} {'Ret%':>7} {'Candle':>6}  "
        f"{'P_sz':>5} {'C_sz':>5}  "
        f"{'Put PnL%':>9} {'Call PnL%':>10}  "
        f"{'PutGrossL%':>11} {'CallGrossL%':>12}  "
        f"{'CumPnL%':>8}  {'Next P_sz':>9} {'Next C_sz':>9}  Reasoning"
    )
    print("-" * 160)

    raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                      interval="1mo", auto_adjust=True, progress=False)
    close_col = raw["Close"]
    if isinstance(close_col, pd.DataFrame):
        close_col = close_col.iloc[:, 0]
    prices = close_col.dropna()
    returns = prices.pct_change().dropna()

    cum_pnl         = 0.0
    put_gross_loss  = 0.0
    call_gross_loss = 0.0
    put_size        = 1
    call_size       = 1
    recovery        = False
    first_month     = True

    for i, (date, r) in enumerate(returns.items()):
        r = float(r)
        candle = "UP  " if r >= 0 else "DOWN"

        put_pnl_pu  = PREMIUM + min(r, 0.0)
        call_pnl_pu = PREMIUM - max(r, 0.0)
        put_pnl     = put_size  * put_pnl_pu
        call_pnl    = call_size * call_pnl_pu
        cum_pnl    += put_pnl + call_pnl

        if put_pnl_pu  < 0.0: put_gross_loss  += put_size  * abs(put_pnl_pu)
        if call_pnl_pu < 0.0: call_gross_loss += call_size * abs(call_pnl_pu)

        next_put, next_call, recovery = _next_sizes(
            r, cum_pnl, put_gross_loss, call_gross_loss, first_month
        )

        # ── Build human-readable reasoning ────────────────────────────────────
        if cum_pnl >= 0.0 and not first_month:
            reason = "RESET — cum PnL ≥ 0"
        elif r >= 0.0:
            if call_gross_loss > 0.0:
                reason = (
                    f"UP: call gross loss={call_gross_loss*100:.2f}% "
                    f"→ put_sz=ceil({call_gross_loss*100:.2f}/{PREMIUM*100:.0f})={next_put}"
                )
            else:
                reason = "UP: no call loss yet → put_sz=1"
        else:
            if put_gross_loss > 0.0:
                reason = (
                    f"DOWN: put gross loss={put_gross_loss*100:.2f}% "
                    f"→ call_sz=ceil({put_gross_loss*100:.2f}/{PREMIUM*100:.0f})={next_call}"
                )
            else:
                reason = "DOWN: no put loss yet → call_sz=1"

        print(
            f"{date.strftime('%Y-%m'):<10} {r*100:>7.2f} {candle:>6}  "
            f"{put_size:>5} {call_size:>5}  "
            f"{put_pnl*100:>9.2f} {call_pnl*100:>10.2f}  "
            f"{put_gross_loss*100:>11.2f} {call_gross_loss*100:>12.2f}  "
            f"{cum_pnl*100:>8.2f}  {next_put:>9} {next_call:>9}  {reason}"
        )

        if not recovery:
            put_gross_loss  = 0.0
            call_gross_loss = 0.0

        put_size    = next_put
        call_size   = next_call
        first_month = False

    print(f"\nFinal cumulative PnL: {cum_pnl*100:.2f}%")
    print(f"{'='*80}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    # ── Trace mode: python strategy.py --trace AAPL ───────────────────────────
    if len(sys.argv) >= 2 and sys.argv[1] == "--trace":
        ticker = sys.argv[2] if len(sys.argv) >= 3 else "AAPL"
        trace_stock(ticker)
        return

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

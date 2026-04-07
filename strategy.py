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

import io
import sys
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import boto3

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────────
FALLBACK_PREMIUM = 0.03      # fallback if no S3 data available for a month
START_DATE       = "2015-01-01"
END_DATE         = "2024-12-31"
TOP_N            = 100
MAX_SIZE         = 5_000     # safety cap on position size (units)

import os
AWS_KEY    = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET = os.environ["AWS_SECRET_ACCESS_KEY"]
S3_BUCKET  = os.environ.get("S3_BUCKET", "s3bucketmz")
S3_PUT     = "optionsData"       # put premiums
S3_CALL    = "optionsDataCall"   # call premiums

# ── Sector-based proxy: for tickers without S3 data use closest available ─────
# Proxy ticker must be present in the S3 dataset (42 tickers).
PROXY_MAP = {
    # Semiconductors / hardware
    "AMD":    "NVDA",  "MU":    "NVDA",  "AMAT":  "AVGO",
    "KLAC":   "AVGO",  "LRCX":  "AVGO",  "TXN":   "AVGO",
    "ADI":    "AVGO",  "QCOM":  "QCOM",  "APH":   "AVGO",
    # Large-cap tech / software
    "ADBE":   "MSFT",  "ADP":   "IBM",   "CSCO":  "IBM",
    "PANW":   "CRM",   "FI":    "MA",
    # Consumer / retail
    "MCD":    "KO",    "NKE":   "NKE",   "LOW":   "HD",
    "TJX":    "WMT",   "MDLZ":  "PEP",   "PM":    "PEP",
    # Healthcare
    "BMY":    "ABBV",  "AMGN":  "ABBV",  "GILD":  "ABBV",
    "REGN":   "ABBV",  "VRTX":  "ABBV",  "ZTS":   "ABBV",
    "BSX":    "ABT",   "DHR":   "ABT",   "ISRG":  "ABT",
    "SYK":    "ABT",   "ELV":   "UNH",   "CI":    "UNH",
    # Financials
    "GS":     "JPM",   "MS":    "JPM",   "BLK":   "JPM",
    "SCHW":   "JPM",   "AXP":   "MA",    "SPGI":  "JPM",
    "MCO":    "JPM",   "CME":   "JPM",   "CB":    "JPM",
    "PGR":    "JPM",
    # Industrials / materials
    "GE":     "SPY",   "CAT":   "SPY",   "HON":   "SPY",
    "RTX":    "SPY",   "UNP":   "SPY",   "DE":    "SPY",
    "ETN":    "SPY",   "EMR":   "SPY",   "ITW":   "SPY",
    "LIN":    "SPY",   "SHW":   "SPY",   "ECL":   "PG",
    "APH":    "SPY",
    # Utilities / real estate
    "NEE":    "KO",    "DUK":   "KO",    "SO":    "KO",
    "CEG":    "XOM",   "PLD":   "SPY",
    # Telecom / media
    "T":      "CMCSA", "DIS":   "DIS",
    # Other
    "BRK-B":  "SPY",   "PYPL":  "MA",
}

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

# ── S3 Premium Loading ─────────────────────────────────────────────────────────

def _s3_history_key(prefix: str, ticker: str) -> str:
    """Return the S3 key for a ticker's history_summary.csv (handles path quirks)."""
    # Most tickers: prefix/TICKER/TICKER/TICKER_history_summary.csv
    # Exception: ACN put has prefix/ACN/ACN_history_summary.csv
    standard = f"{prefix}/{ticker}/{ticker}/{ticker}_history_summary.csv"
    short    = f"{prefix}/{ticker}/{ticker}_history_summary.csv"
    return standard, short


def load_s3_premiums() -> dict[str, dict[str, dict]]:
    """
    Load all history_summary CSVs from S3.

    Returns:
      premiums[ticker]['put'][period]  = put  premium as fraction (e.g. 0.028)
      premiums[ticker]['call'][period] = call premium as fraction
      premiums[ticker]['put_avg']      = mean put  premium fraction
      premiums[ticker]['call_avg']     = mean call premium fraction
    where period is a pandas Period('M').
    """
    print("Loading real options premium data from S3 …")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        region_name="us-east-1",
    )
    paginator = s3.get_paginator("list_objects_v2")
    premiums: dict[str, dict] = {}

    for prefix, side in [(S3_PUT, "put"), (S3_CALL, "call")]:
        count = 0
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"{prefix}/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith("history_summary.csv"):
                    continue
                ticker = key.split("/")[1]
                try:
                    raw = s3.get_object(Bucket=S3_BUCKET, Key=key)
                    df  = pd.read_csv(io.BytesIO(raw["Body"].read()))
                    df["observation_date"] = pd.to_datetime(df["observation_date"])
                    df["prem_frac"] = df["entry_premium"] / df["stock_price"]
                    df["month"]     = df["observation_date"].dt.to_period("M")
                    # One row per month (take last entry if duplicates)
                    monthly = (
                        df.sort_values("observation_date")
                          .groupby("month")["prem_frac"]
                          .last()
                    )
                    avg = df["prem_frac"].mean()
                    rec = premiums.setdefault(ticker, {})
                    rec[side]          = monthly.to_dict()
                    rec[f"{side}_avg"] = avg
                    count += 1
                except Exception as e:
                    print(f"  Warning: could not load {key}: {e}")
        print(f"  {side:4s}: loaded {count} tickers")

    print(f"  → {len(premiums)} tickers with S3 premium data")
    return premiums


def get_premium(
    premiums: dict,
    ticker: str,
    month: "pd.Period",
    side: str,          # 'put' or 'call'
) -> float:
    """
    Return the ATM premium fraction for (ticker, month, side).

    Look-up priority:
      1. Exact ticker + month in S3
      2. Exact ticker average (month outside S3 range)
      3. Proxy ticker (same sector, in S3) — exact month then avg
      4. Global fallback constant FALLBACK_PREMIUM
    """
    def _from_rec(rec, m):
        if m in rec.get(side, {}):
            return rec[side][m]
        avg_key = f"{side}_avg"
        if avg_key in rec:
            return rec[avg_key]
        return None

    # 1 & 2: own ticker
    if ticker in premiums:
        v = _from_rec(premiums[ticker], month)
        if v is not None:
            return v

    # 3: proxy
    proxy = PROXY_MAP.get(ticker)
    if proxy and proxy in premiums:
        v = _from_rec(premiums[proxy], month)
        if v is not None:
            return v

    # 4: fallback
    return FALLBACK_PREMIUM


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
    itm_gross_loss: float,
    recovery_premium: float,
) -> tuple[int, int]:
    """
    Compute (put_size, call_size) for the NEXT month.

    recovery_premium: the premium fraction of the side being sized up
      (used so that the number of units is calibrated to the right premium).

    Recovery size = ceil(ITM_gross_loss / recovery_premium), minimum 1.
    """
    denom = recovery_premium if recovery_premium > 0 else FALLBACK_PREMIUM
    rec   = max(1, int(np.ceil(itm_gross_loss / denom)))
    rec   = min(rec, MAX_SIZE)
    if r >= 0.0:     # UP   → size PUTS (put premium drives sizing), call = 1
        return rec, 1
    else:            # DOWN → size CALLS (call premium drives sizing), put = 1
        return 1, rec


def simulate_stock(
    ticker: str,
    prices: pd.Series,
    premiums: dict,
) -> pd.DataFrame:
    """
    Simulate the vol-selling strategy for a single stock using real premiums.

    premiums: output of load_s3_premiums() — per-month ATM premium fractions.
    For months / tickers not in S3, falls back to per-ticker avg or FALLBACK_PREMIUM.

    PnL model per unit per month:
      put_pnl_pu  = put_prem  + min(r, 0)
      call_pnl_pu = call_prem - max(r, 0)

    Sizing: size = ceil(ITM_gross_loss / next_side_premium)
    """
    prices = prices.dropna()
    if len(prices) < 3:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    n       = len(returns)

    records     = []
    episode_pnl = 0.0
    total_pnl   = 0.0
    put_size    = 1
    call_size   = 1
    # We track which premium will be used for sizing next month's recovery side
    next_put_prem  = FALLBACK_PREMIUM
    next_call_prem = FALLBACK_PREMIUM

    for i in range(n):
        r    = float(returns.iloc[i])
        date = returns.index[i]
        month = pd.Period(date, "M")

        # ── Fetch real premiums for this month ────────────────────────────────
        put_prem  = get_premium(premiums, ticker, month, "put")
        call_prem = get_premium(premiums, ticker, month, "call")

        # ── Episode reset at base size ────────────────────────────────────────
        if put_size == 1 and call_size == 1:
            episode_pnl = 0.0

        # ── PnL this month ────────────────────────────────────────────────────
        put_pnl_pu  = put_prem  + min(r, 0.0)
        call_pnl_pu = call_prem - max(r, 0.0)
        put_pnl     = put_size  * put_pnl_pu
        call_pnl    = call_size * call_pnl_pu
        month_pnl   = put_pnl + call_pnl

        episode_pnl += month_pnl
        total_pnl   += month_pnl

        # ── ITM gross loss from this month's losing side ──────────────────────
        if r >= 0.0:
            itm_gross_loss = call_size * max(0.0, r - call_prem)   # call ITM
            # Next month: size PUTS; use next month's put premium for sizing
            # (best estimate = current month's put premium, same ticker)
            recovery_prem  = put_prem
        else:
            itm_gross_loss = put_size  * max(0.0, -r - put_prem)   # put  ITM
            recovery_prem  = call_prem

        max_hit = (put_size >= MAX_SIZE or call_size >= MAX_SIZE)

        records.append({
            "date":               date,
            "return_pct":         round(r            * 100, 4),
            "put_prem_pct":       round(put_prem      * 100, 4),
            "call_prem_pct":      round(call_prem     * 100, 4),
            "put_size":           put_size,
            "call_size":          call_size,
            "put_pnl_pct":        round(put_pnl       * 100, 4),
            "call_pnl_pct":       round(call_pnl      * 100, 4),
            "itm_gross_loss_pct": round(itm_gross_loss * 100, 4),
            "month_pnl_pct":      round(month_pnl     * 100, 4),
            "episode_cum_pnl_pct":round(episode_pnl   * 100, 4),
            "total_cum_pnl_pct":  round(total_pnl     * 100, 4),
            "in_recovery":        episode_pnl < 0.0,
            "max_size_hit":       max_hit,
        })

        # ── Next month's sizes ────────────────────────────────────────────────
        put_size, call_size = _next_sizes(r, itm_gross_loss, recovery_prem)

    return pd.DataFrame(records)


# ── Portfolio Aggregation ──────────────────────────────────────────────────────

def run_portfolio(
    closes: pd.DataFrame,
    premiums: dict,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Simulate strategy for every ticker; aggregate equally-weighted portfolio PnL.
    """
    stock_results: dict[str, pd.DataFrame] = {}

    for ticker in closes.columns:
        df = simulate_stock(ticker, closes[ticker], premiums)
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
        total_col     = df["total_cum_pnl_pct"]
        max_drawdown  = (total_col - total_col.cummax()).min()
        max_put_size  = df["put_size"].max()
        max_call_size = df["call_size"].max()
        max_hit       = df["max_size_hit"].any()
        recovery_pct  = df["in_recovery"].mean() * 100
        final_cum_pnl = total_col.iloc[-1]

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
    print(f"  Premium source     : S3 real ATM options data (fallback {FALLBACK_PREMIUM*100:.1f}%)")
    print(f"  Backtest period    : {START_DATE}  →  {END_DATE}")
    print(f"  Universe           : top {TOP_N} SPX single equities")
    print(f"  Sizing rule        : UP candle → bigger PUT size | DOWN → bigger CALL")
    print(f"  Recovery sizing    : ceil(ITM_gross_loss / next_side_premium)")
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

def trace_stock(ticker: str, premiums: dict) -> None:
    """
    Fetch data for one ticker and print a month-by-month sizing walk-through
    using real S3 premiums where available.
    """
    print(f"\n{'='*110}")
    print(f"  STEP-BY-STEP SIZING TRACE — {ticker}  (real S3 premiums)")
    print(f"{'='*110}")
    hdr = (
        f"{'Month':<10} {'Ret%':>7} {'Cndl':>4}  "
        f"{'PutPrem%':>9} {'CallPrem%':>10}  "
        f"{'P_sz':>5} {'C_sz':>5}  "
        f"{'Put PnL%':>9} {'Call PnL%':>10}  "
        f"{'ITM_loss%':>10}  {'Month%':>7} {'EpisodePnL%':>12}  "
        f"{'NxtP':>5} {'NxtC':>5}  Reasoning"
    )
    print(hdr)
    print("-" * len(hdr))

    raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                      interval="1mo", auto_adjust=True, progress=False)
    close_col = raw["Close"]
    if isinstance(close_col, pd.DataFrame):
        close_col = close_col.iloc[:, 0]
    prices  = close_col.dropna()
    returns = prices.pct_change().dropna()

    episode_pnl = 0.0
    total_pnl   = 0.0
    put_size    = 1
    call_size   = 1

    for date, r in returns.items():
        r     = float(r)
        candle = "UP" if r >= 0 else "DN"
        month  = pd.Period(date, "M")

        put_prem  = get_premium(premiums, ticker, month, "put")
        call_prem = get_premium(premiums, ticker, month, "call")

        if put_size == 1 and call_size == 1:
            episode_pnl = 0.0

        put_pnl_pu  = put_prem  + min(r, 0.0)
        call_pnl_pu = call_prem - max(r, 0.0)
        put_pnl     = put_size  * put_pnl_pu
        call_pnl    = call_size * call_pnl_pu
        month_pnl   = put_pnl + call_pnl
        episode_pnl += month_pnl
        total_pnl   += month_pnl

        if r >= 0.0:
            itm_loss     = call_size * max(0.0, r - call_prem)
            recovery_prem = put_prem
            itm_side      = "call"
        else:
            itm_loss     = put_size  * max(0.0, -r - put_prem)
            recovery_prem = call_prem
            itm_side      = "put"

        next_put, next_call = _next_sizes(r, itm_loss, recovery_prem)

        if itm_loss == 0.0:
            reason = f"{candle}: {itm_side} OTM → both stay 1"
        elif r >= 0.0:
            reason = (
                f"UP: call ITM={itm_loss*100:.2f}% "
                f"→ put_sz=ceil({itm_loss*100:.2f}/{recovery_prem*100:.2f}%)={next_put}"
            )
        else:
            reason = (
                f"DN: put ITM={itm_loss*100:.2f}% "
                f"→ call_sz=ceil({itm_loss*100:.2f}/{recovery_prem*100:.2f}%)={next_call}"
            )

        print(
            f"{date.strftime('%Y-%m'):<10} {r*100:>7.2f} {candle:>4}  "
            f"{put_prem*100:>9.2f} {call_prem*100:>10.2f}  "
            f"{put_size:>5} {call_size:>5}  "
            f"{put_pnl*100:>9.2f} {call_pnl*100:>10.2f}  "
            f"{itm_loss*100:>10.2f}  {month_pnl*100:>7.2f} {episode_pnl*100:>12.2f}  "
            f"{next_put:>5} {next_call:>5}  {reason}"
        )

        put_size  = next_put
        call_size = next_call

    print(f"\nTotal backtest PnL: {total_pnl*100:.2f}%")
    print(f"{'='*110}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    # 0. Load real premiums from S3 (shared by all modes)
    premiums = load_s3_premiums()

    # ── Trace mode: python strategy.py --trace AAPL ───────────────────────────
    if len(sys.argv) >= 2 and sys.argv[1] == "--trace":
        ticker = sys.argv[2] if len(sys.argv) >= 3 else "AAPL"
        trace_stock(ticker, premiums)
        return

    tickers = TOP100_TICKERS[:TOP_N]

    # 1. Fetch price data
    closes = fetch_monthly_prices(tickers, START_DATE, END_DATE)

    # 2. Simulate per stock + aggregate portfolio
    print("Running strategy simulation …")
    stock_results, portfolio_df = run_portfolio(closes, premiums)
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

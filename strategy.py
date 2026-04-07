#!/usr/bin/env python3
"""
SPX Single Equity Vol Selling Strategy Simulator
=================================================

Strategy rules:
  1. Universe  : 100 biggest SPX single equities
  2. Timeframe : monthly candles
  3. Each month sell ONE side only — chosen by the PREVIOUS candle:
       Previous candle UP   → sell PUT  this month  (stock rose, put is safer)
       Previous candle DOWN → sell CALL this month  (stock fell, call is safer)
  4. Size = max(1, ceil(accumulated_loss / premium))
       accumulated_loss = running PnL deficit since last reset
  5. Reset size to 1 and clear accumulated loss when episode PnL turns ≥ 0.

PnL model per unit per month:
  put_pnl_pu  = put_prem  + min(r, 0)   →  earns premium, unbounded loss below
  call_pnl_pu = call_prem - max(r, 0)   →  earns premium, unbounded loss above
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
    # Industrials / materials  (use XOM ~3% or IBM ~2.8%, NOT SPY 1.7%)
    "GE":     "XOM",   "CAT":   "XOM",   "HON":   "IBM",
    "RTX":    "XOM",   "UNP":   "XOM",   "DE":    "XOM",
    "ETN":    "XOM",   "EMR":   "XOM",   "ITW":   "IBM",
    "LIN":    "ABT",   "SHW":   "IBM",   "ECL":   "PG",
    "APH":    "IBM",
    # Utilities / real estate  (use KO ~1.9% — low vol, similar to utilities)
    "NEE":    "KO",    "DUK":   "KO",    "SO":    "KO",
    "CEG":    "XOM",   "PLD":   "IBM",
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

def _calc_size(accumulated_loss: float, premium: float) -> int:
    """Units needed so premium covers accumulated_loss in one month."""
    denom = premium if premium > 0 else FALLBACK_PREMIUM
    return min(MAX_SIZE, max(1, int(np.ceil(accumulated_loss / denom))))


def simulate_stock(
    ticker: str,
    prices: pd.Series,
    premiums: dict,
) -> pd.DataFrame:
    """
    One-sided vol-selling strategy with cumulative-loss recovery sizing.

    Each month sells ONE leg chosen by the PREVIOUS candle:
      prev UP   → sell PUT   prev DOWN → sell CALL

    Sizing rule (true cumulative martingale):
      cumulated_loss = running total PnL deficit of the current episode.
      Every trade outcome (win or loss) adjusts cumulated_loss.
      size = ceil(cumulated_loss / premium)
        → if this month wins at full premium, it exactly wipes the deficit.
      When cumulated_loss reaches 0 (episode recovered), reset size to 1.

    Because recovery-trade losses also compound into cumulated_loss, the size
    is always sized to recover the TOTAL deficit in one good month.
    MAX_SIZE caps runaway sizes.
    """
    prices = prices.dropna()
    if len(prices) < 3:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    n       = len(returns)

    records        = []
    total_pnl      = 0.0
    episode_pnl    = 0.0   # running sum of month_pnl in current episode (fractions)
    sell_put       = True  # default: first trade sells a put (prior candle assumed UP)

    for i in range(n):
        r     = float(returns.iloc[i])
        date  = returns.index[i]
        month = pd.Period(date, "M")

        side = "put" if sell_put else "call"
        prem = get_premium(premiums, ticker, month, side)

        # ── Cumulated loss = deficit still owed from this episode ─────────────
        cumulated_loss = max(0.0, -episode_pnl)
        in_recovery    = cumulated_loss > 0.0

        # ── Size: enough units so one premium-winning month covers the deficit ─
        size    = _calc_size(cumulated_loss, prem)
        max_hit = size >= MAX_SIZE

        # ── PnL this month ────────────────────────────────────────────────────
        if sell_put:
            pnl_pu = prem + min(r, 0.0)
        else:
            pnl_pu = prem - max(r, 0.0)

        month_pnl    = size * pnl_pu
        episode_pnl += month_pnl
        total_pnl   += month_pnl

        # Reset episode when deficit is cleared
        if episode_pnl >= 0.0:
            episode_pnl = 0.0

        records.append({
            "date":                date,
            "selling":             side,
            "prem_pct":            round(prem            * 100, 4),
            "size":                size,
            "return_pct":          round(r                * 100, 4),
            "pnl_pu_pct":          round(pnl_pu           * 100, 4),
            "month_pnl_pct":       round(month_pnl        * 100, 4),
            "cumulated_loss_pct":  round(cumulated_loss   * 100, 4),
            "episode_cum_pnl_pct": round(episode_pnl      * 100, 4),
            "total_cum_pnl_pct":   round(total_pnl        * 100, 4),
            "in_recovery":         in_recovery,
            "max_size_hit":        max_hit,
        })

        # ── Next month direction ──────────────────────────────────────────────
        sell_put = (r >= 0.0)

    return pd.DataFrame(records)


# ── Portfolio Aggregation ──────────────────────────────────────────────────────

def run_portfolio(
    closes: pd.DataFrame,
    premiums: dict,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Simulate strategy for every ticker.

    Portfolio model:
      • Each stock receives 1/100 of total capital at base (size=1).
      • In recovery, that stock's capital multiplies by its size.
      • Monthly portfolio return = sum(size_i × pnl_pu_i) / 100   [in %]
      • Capital deployed        = sum(size_i) / 100               [leverage ratio]

    Returns (stock_results dict, portfolio_df with monthly summary).
    """
    stock_results: dict[str, pd.DataFrame] = {}

    for ticker in closes.columns:
        df = simulate_stock(ticker, closes[ticker], premiums)
        if not df.empty:
            stock_results[ticker] = df

    if not stock_results:
        raise RuntimeError("No valid stock simulations produced.")

    # Aggregate across stocks per calendar month
    monthly_buckets: dict = {}   # date → accumulators

    for ticker, df in stock_results.items():
        for _, row in df.iterrows():
            date = row["date"]
            b = monthly_buckets.setdefault(
                date,
                {"ret_sum": 0.0, "size_sum": 0, "n_stocks": 0, "n_recovery": 0},
            )
            b["ret_sum"]    += float(row["size"]) * float(row["pnl_pu_pct"]) / 100.0
            b["size_sum"]   += int(row["size"])
            b["n_stocks"]   += 1
            if bool(row["in_recovery"]):
                b["n_recovery"] += 1

    rows = []
    cum_return = 0.0
    for date in sorted(monthly_buckets.keys()):
        b = monthly_buckets[date]
        monthly_ret = b["ret_sum"]   # already divided by 100 (portfolio %)
        cum_return += monthly_ret
        rows.append({
            "date":                    date,
            "monthly_return_pct":      round(monthly_ret,            4),
            "cumulative_return_pct":   round(cum_return,             4),
            "capital_deployed":        round(b["size_sum"] / 100.0,  2),
            "num_stocks":              b["n_stocks"],
            "num_stocks_in_recovery":  b["n_recovery"],
        })

    portfolio_df = pd.DataFrame(rows)
    return stock_results, portfolio_df


# ── Trade History ──────────────────────────────────────────────────────────────

def save_history_csv(stock_results: dict[str, pd.DataFrame]) -> None:
    """
    Save one row per (date, ticker) trade to history.csv.

    Columns:
      date, ticker, selling_side, prem_pct, size,
      capital_allocated_pct  (= size × 1%  of portfolio),
      return_pct, pnl_pu_pct,
      pnl_contribution_pct   (= size × pnl_pu / 100),
      in_recovery
    """
    rows = []
    for ticker, df in stock_results.items():
        for _, row in df.iterrows():
            sz  = int(row["size"])
            ppu = float(row["pnl_pu_pct"])
            rows.append({
                "date":                   row["date"],
                "ticker":                 ticker,
                "selling_side":           row["selling"],
                "prem_pct":               row["prem_pct"],
                "size":                   sz,
                "capital_allocated_pct":  sz,          # each unit = 1% of portfolio
                "return_pct":             row["return_pct"],
                "pnl_pu_pct":             ppu,
                "pnl_contribution_pct":   round(sz * ppu / 100.0, 6),
                "in_recovery":            bool(row["in_recovery"]),
            })

    history = (
        pd.DataFrame(rows)
        .sort_values(["date", "ticker"])
        .reset_index(drop=True)
    )
    history.to_csv("history.csv", index=False)
    print(f"  history.csv written  ({len(history):,} rows)")


# ── Risk Statistics ────────────────────────────────────────────────────────────

def compute_risk_stats(
    portfolio_df: pd.DataFrame,
    rf_annual: float = 0.04,
) -> dict:
    """
    Compute standard risk/return statistics on the monthly portfolio return series.

    Returns a dict with annualised return, vol, Sharpe, Sortino, max drawdown,
    Calmar, VaR 95/99%, CVaR 95%, win rate, best/worst month.
    """
    mr = portfolio_df["monthly_return_pct"].values / 100.0   # fractions

    n            = len(mr)
    mean_mo      = np.mean(mr)
    std_mo       = np.std(mr, ddof=1) if n > 1 else 0.0
    ann_ret      = mean_mo  * 12
    ann_vol      = std_mo   * np.sqrt(12)
    rf_mo        = rf_annual / 12

    # Sharpe (vs 4% RFR)
    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0.0

    # Sortino: downside vol uses returns below monthly RFR
    down = mr[mr < rf_mo]
    down_vol = np.std(down, ddof=1) * np.sqrt(12) if len(down) > 1 else 0.0
    sortino  = (ann_ret - rf_annual) / down_vol if down_vol > 0 else 0.0

    # Max drawdown on cumulative return (simple sum, not compounded)
    cum = np.cumsum(mr)
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    # VaR / CVaR
    var95  = float(np.percentile(mr, 5))
    var99  = float(np.percentile(mr, 1))
    tail95 = mr[mr <= var95]
    cvar95 = float(tail95.mean()) if len(tail95) > 0 else var95

    win_rate = float((mr > 0).mean() * 100)

    return {
        "n_months":               n,
        "ann_return_pct":         round(ann_ret   * 100, 2),
        "ann_vol_pct":            round(ann_vol   * 100, 2),
        "sharpe_4pct_rf":         round(sharpe,          3),
        "sortino_4pct_rf":        round(sortino,         3),
        "max_drawdown_pct":       round(max_dd    * 100, 2),
        "calmar":                 round(calmar,          3),
        "var_95_pct":             round(var95     * 100, 2),
        "var_99_pct":             round(var99     * 100, 2),
        "cvar_95_pct":            round(cvar95    * 100, 2),
        "win_rate_pct":           round(win_rate,        1),
        "best_month_pct":         round(float(mr.max()) * 100, 2),
        "worst_month_pct":        round(float(mr.min()) * 100, 2),
        "avg_monthly_return_pct": round(mean_mo   * 100, 4),
    }


# ── Summary Statistics ─────────────────────────────────────────────────────────

def compute_summary(stock_results: dict[str, pd.DataFrame], portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-stock and portfolio summary statistics."""
    rows = []
    for ticker, df in stock_results.items():
        total_months  = len(df)
        total_pnl_v   = df["month_pnl_pct"].sum()
        avg_monthly   = df["month_pnl_pct"].mean()
        win_rate      = (df["month_pnl_pct"] > 0).mean() * 100
        total_col     = df["total_cum_pnl_pct"]
        max_drawdown  = (total_col - total_col.cummax()).min()
        max_size      = df["size"].max()
        max_hit       = df["max_size_hit"].any()
        recovery_pct  = df["in_recovery"].mean() * 100
        final_cum_pnl = total_col.iloc[-1]
        avg_prem      = df["prem_pct"].mean()

        rows.append({
            "ticker":             ticker,
            "months":             total_months,
            "total_pnl_pct":      round(total_pnl_v,  2),
            "final_cum_pnl_pct":  round(final_cum_pnl, 2),
            "avg_monthly_pnl_pct":round(avg_monthly,   4),
            "avg_prem_pct":       round(avg_prem,       2),
            "win_rate_pct":       round(win_rate,       1),
            "max_drawdown_pct":   round(max_drawdown,   2),
            "max_size":           int(max_size),
            "max_size_hit":       max_hit,
            "pct_months_recovery":round(recovery_pct,  1),
        })

    summary = pd.DataFrame(rows).sort_values("total_pnl_pct", ascending=False)

    # Add portfolio row
    port_row = {
        "ticker":             "PORTFOLIO (1/100 capital)",
        "months":             len(portfolio_df),
        "total_pnl_pct":      round(portfolio_df["monthly_return_pct"].sum(), 2),
        "final_cum_pnl_pct":  round(portfolio_df["cumulative_return_pct"].iloc[-1], 2),
        "avg_monthly_pnl_pct":round(portfolio_df["monthly_return_pct"].mean(), 4),
        "avg_prem_pct":       "–",
        "win_rate_pct":       round((portfolio_df["monthly_return_pct"] > 0).mean() * 100, 1),
        "max_drawdown_pct":   round(
            (portfolio_df["cumulative_return_pct"] -
             portfolio_df["cumulative_return_pct"].cummax()).min(), 2),
        "max_size":           "–",
        "max_size_hit":       "–",
        "pct_months_recovery":"–",
    }
    summary = pd.concat([pd.DataFrame([port_row]), summary], ignore_index=True)

    return summary


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_monthly_table(portfolio_df: pd.DataFrame) -> None:
    """Print the month-by-month portfolio return table."""
    print("\n" + "=" * 80)
    print("  MONTHLY PORTFOLIO RETURNS")
    print("=" * 80)
    hdr = (
        f"{'Month':<10}  {'Return%':>8}  {'Cum%':>8}  "
        f"{'CapDeploy':>9}  {'Stocks':>6}  {'InRecov':>7}"
    )
    print(hdr)
    print("-" * 80)
    for _, row in portfolio_df.iterrows():
        date_str = row["date"].strftime("%Y-%m") if hasattr(row["date"], "strftime") else str(row["date"])[:7]
        print(
            f"{date_str:<10}  {row['monthly_return_pct']:>8.3f}  "
            f"{row['cumulative_return_pct']:>8.3f}  "
            f"{row['capital_deployed']:>9.2f}  "
            f"{row['num_stocks']:>6}  "
            f"{row['num_stocks_in_recovery']:>7}"
        )
    print("=" * 80)


def print_risk_stats(stats: dict) -> None:
    """Print the risk statistics block."""
    print("\n" + "=" * 50)
    print("  RISK STATISTICS  (portfolio, 1/100 per stock)")
    print("=" * 50)
    print(f"  Months               : {stats['n_months']}")
    print(f"  Annualised return    : {stats['ann_return_pct']:>8.2f} %")
    print(f"  Annualised vol       : {stats['ann_vol_pct']:>8.2f} %")
    print(f"  Sharpe (4% RF)       : {stats['sharpe_4pct_rf']:>8.3f}")
    print(f"  Sortino (4% RF)      : {stats['sortino_4pct_rf']:>8.3f}")
    print(f"  Max drawdown         : {stats['max_drawdown_pct']:>8.2f} %")
    print(f"  Calmar               : {stats['calmar']:>8.3f}")
    print(f"  VaR 95%              : {stats['var_95_pct']:>8.2f} %")
    print(f"  VaR 99%              : {stats['var_99_pct']:>8.2f} %")
    print(f"  CVaR 95%             : {stats['cvar_95_pct']:>8.2f} %")
    print(f"  Win rate             : {stats['win_rate_pct']:>8.1f} %")
    print(f"  Best month           : {stats['best_month_pct']:>8.2f} %")
    print(f"  Worst month          : {stats['worst_month_pct']:>8.2f} %")
    print(f"  Avg monthly return   : {stats['avg_monthly_return_pct']:>8.4f} %")
    print("=" * 50)


def print_summary(summary: pd.DataFrame, portfolio_df: pd.DataFrame) -> None:
    port = summary.iloc[0]
    print("\n" + "=" * 72)
    print("  SPX SINGLE-EQUITY VOL SELLING STRATEGY  —  SIMULATION RESULTS")
    print("=" * 72)
    print(f"  Premium source     : S3 real ATM options data (fallback {FALLBACK_PREMIUM*100:.1f}%)")
    print(f"  Backtest period    : {START_DATE}  →  {END_DATE}")
    print(f"  Universe           : top {TOP_N} SPX single equities")
    print(f"  Capital model      : 1/100 per stock; recovery trades multiply that stock's capital")
    print(f"  Sizing rule        : UP candle → sell PUT | DOWN → sell CALL")
    print(f"  Recovery sizing    : ceil(last_base_ITM_loss / premium); anti-blowup")
    print("=" * 72)
    print(f"\nPORTFOLIO (1/100 capital per stock)")
    print(f"  Final cum return   : {port['final_cum_pnl_pct']:>8.2f} %")
    print(f"  Avg monthly return : {port['avg_monthly_pnl_pct']:>8.4f} %")
    print(f"  Win rate           : {port['win_rate_pct']:>8.1f} %")
    print(f"  Max drawdown       : {port['max_drawdown_pct']:>8.2f} %")
    max_cap = portfolio_df["capital_deployed"].max()
    print(f"  Max capital deploy : {max_cap:>8.2f}x  (leverage vs. base 1.0×)")
    print()
    print("TOP 10 STOCKS (by total PnL % contribution to portfolio)")
    cols = ["ticker", "total_pnl_pct", "avg_monthly_pnl_pct", "avg_prem_pct",
            "win_rate_pct", "max_drawdown_pct", "max_size", "pct_months_recovery"]
    stocks = summary[summary["ticker"] != "PORTFOLIO (1/100 capital)"]
    top10  = stocks.head(10)
    print(top10[cols].to_string(index=False))
    print()
    print("BOTTOM 10 STOCKS (by total PnL % contribution to portfolio)")
    bot10 = stocks.tail(10)
    print(bot10[cols].to_string(index=False))

    # Stocks that hit the max-size cap
    capped = summary[summary["max_size_hit"] == True]
    if not capped.empty:
        print(f"\n  {len(capped)} stock(s) hit the MAX_SIZE={MAX_SIZE} cap:")
        print("  " + ", ".join(capped["ticker"].tolist()))
    print("=" * 72)


# ── Single-Stock Trace ─────────────────────────────────────────────────────────

def trace_stock(ticker: str, premiums: dict) -> None:
    """Month-by-month sizing walk-through for a single ticker."""
    print(f"\n{'='*105}")
    print(f"  STEP-BY-STEP SIZING TRACE — {ticker}  (real S3 premiums, one-sided)")
    print(f"{'='*105}")
    hdr = (
        f"{'Month':<10} {'Ret%':>7} {'Cndl':>4}  "
        f"{'Sell':>4} {'Prem%':>6} {'Size':>6}  "
        f"{'PnL/u%':>8} {'Month%':>8} {'EpisodePnL%':>12} {'TotalPnL%':>10}  "
        f"{'Nxt':>4}  Reasoning"
    )
    print(hdr)
    print("-" * len(hdr))

    raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                      interval="1mo", auto_adjust=True, progress=False)
    close_col = raw["Close"]
    if isinstance(close_col, pd.DataFrame):
        close_col = close_col.iloc[:, 0]
    returns = close_col.dropna().pct_change().dropna()

    total_pnl   = 0.0
    episode_pnl = 0.0
    sell_put    = True

    for date, r in returns.items():
        r      = float(r)
        candle = "UP" if r >= 0 else "DN"
        month  = pd.Period(date, "M")
        side   = "put" if sell_put else "call"
        prem   = get_premium(premiums, ticker, month, side)

        cumulated_loss = max(0.0, -episode_pnl)
        in_recovery    = cumulated_loss > 0.0
        size           = _calc_size(cumulated_loss, prem)

        pnl_pu    = (prem + min(r, 0.0)) if sell_put else (prem - max(r, 0.0))
        month_pnl = size * pnl_pu
        episode_pnl += month_pnl
        total_pnl   += month_pnl

        next_side = "PUT" if r >= 0 else "CALL"
        if not in_recovery:
            reason = f"base sz=1  |  next → {next_side}"
        else:
            reason = (
                f"cumLoss={cumulated_loss*100:.2f}% "
                f"→ ceil({cumulated_loss*100:.2f}/{prem*100:.2f}%)={size}"
                f"  |  next → {next_side}"
            )

        print(
            f"{date.strftime('%Y-%m'):<10} {r*100:>7.2f} {candle:>4}  "
            f"{side.upper():>4} {prem*100:>6.2f} {size:>6}  "
            f"{pnl_pu*100:>8.2f} {month_pnl*100:>8.2f} {episode_pnl*100:>12.2f} {total_pnl*100:>10.2f}  "
            f"{next_side:>4}  {reason}"
        )

        if episode_pnl >= 0.0:
            episode_pnl = 0.0

        sell_put = (r >= 0.0)

    print(f"\nTotal backtest PnL: {total_pnl*100:.2f}%")
    print(f"{'='*105}\n")


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

    # 4. Risk statistics
    risk_stats = compute_risk_stats(portfolio_df)

    # 5. Print reports
    print_summary(summary, portfolio_df)
    print_monthly_table(portfolio_df)
    print_risk_stats(risk_stats)

    # 6. Save outputs
    print("\nSaving outputs …")
    summary.to_csv("summary.csv", index=False)
    portfolio_df.to_csv("portfolio_pnl.csv", index=False)
    save_history_csv(stock_results)

    print(f"\nOutputs written:")
    print("  summary.csv        — per-stock + portfolio summary statistics")
    print("  portfolio_pnl.csv  — monthly portfolio return series")
    print("  history.csv        — full trade history (one row per stock × month)")


if __name__ == "__main__":
    main()

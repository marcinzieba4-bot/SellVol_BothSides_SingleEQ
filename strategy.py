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
MAX_LEVERAGE     = 5.0       # max total capital deployed (uniform_size×n_active/100)
TARGET_DTE       = 30        # standardise all premiums to this DTE
ASSUMED_DTE      = 25        # fallback DTE if not present in S3 data

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
    # Historical large caps added for survivorship-bias fix
    "INTC":   "AVGO",  # semiconductor peer
    "VZ":     "CMCSA", # telecom peer
    "WBA":    "WMT",   # retail/pharmacy
    "CVS":    "UNH",   # healthcare services
    "MO":     "PEP",   # defensive consumer
    "UPS":    "IBM",   # industrials/logistics
    "MMM":    "IBM",   # industrials
    "GM":     "XOM",   # cyclical industrial
    "F":      "XOM",   # cyclical industrial
    "USB":    "JPM",   # regional bank → financials proxy
    "SBUX":   "KO",    # consumer discretionary/staples
    "TGT":    "WMT",   # retail
}

# ── Broader universe for point-in-time top-100 selection ──────────────────────
# Includes 2024 large caps + historical large caps that have since fallen out.
# This prevents survivorship bias from locking in the 2024 winner list.
EXTRA_HISTORICAL = [
    "INTC",   # Intel — was top-10 in 2015 (~$155B), now fallen
    "VZ",     # Verizon — consistently top-20 (~$180-200B) but not in 2024 list
    "WBA",    # Walgreens — was ~$90B (2015-18), now tiny
    "CVS",    # CVS Health — was ~$100B, healthcare conglomerate
    "MO",     # Altria — was ~$120B, defensive tobacco
    "UPS",    # UPS — was ~$90B logistics
    "MMM",    # 3M — was ~$100B (2015-19), now fallen
    "GM",     # General Motors — was ~$55B cyclical
    "F",      # Ford — was ~$50B cyclical
    "USB",    # US Bancorp — was ~$75B regional bank
    "SBUX",   # Starbucks — was ~$70B, now borderline top-100
    "TGT",    # Target — was ~$45-100B retail
]

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

                    # ── DTE scaling: normalise premium to TARGET_DTE days ─────
                    # Prefer dte_at_obs (actual DTE at observation) over 'dte'
                    # which in some datasets stores a negative epoch offset.
                    dte_col = None
                    for _cand in ("dte_at_obs", "dte_at_observation",
                                  "days_to_expiry", "days_to_exp", "dte"):
                        if _cand in df.columns:
                            dte_col = _cand
                            break
                    if dte_col:
                        raw_dte = pd.to_numeric(df[dte_col], errors="coerce")
                        # Only use positive DTE values; fall back to ASSUMED_DTE otherwise
                        df["_dte"] = raw_dte.where(raw_dte > 0, ASSUMED_DTE).fillna(ASSUMED_DTE)
                    else:
                        df["_dte"] = ASSUMED_DTE
                    # formula: prem_scaled = prem_raw × (1 + 0.4 × (TARGET/DTE − 1))
                    df["prem_frac"] *= (1 + 0.4 * (TARGET_DTE / df["_dte"] - 1))

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


# ── Point-in-Time Universe ─────────────────────────────────────────────────────

def build_yearly_universes(
    closes: pd.DataFrame,
    n: int = TOP_N,
) -> dict[int, set]:
    """
    For each year in the backtest, determine which tickers were in the top-N
    by approximate market cap at 31-Jan of that year.

    Market-cap proxy = price_at_jan_end × current_shares_outstanding.
    Using current shares is an approximation; shares change slowly (<15% over
    10 years for most large caps) so the ranking is still far more accurate than
    using the 2024 market-cap ranking for the entire backtest.

    Tickers with no price data at year-start (e.g. CEG spun off in 2022) are
    naturally excluded from early years.
    """
    print("Building point-in-time universes …")

    # Fetch current shares outstanding once per ticker
    shares: dict[str, float] = {}
    print("  Fetching shares outstanding (current, used as proxy) …")
    for ticker in closes.columns:
        try:
            fi = yf.Ticker(ticker).fast_info
            sh = getattr(fi, "shares", None)
            if sh and sh > 0:
                shares[ticker] = float(sh)
        except Exception:
            pass
    print(f"  Got shares for {len(shares)} / {len(closes.columns)} tickers")

    start_year = int(START_DATE[:4])
    end_year   = int(END_DATE[:4])
    yearly: dict[int, set] = {}

    for year in range(start_year, end_year + 1):
        jan_end = f"{year}-01-31"
        mask = closes.index <= jan_end
        if not mask.any():
            yearly[year] = set()
            continue

        jan_prices = closes.loc[mask].iloc[-1]   # last price on/before Jan 31

        mcap: dict[str, float] = {}
        for ticker in closes.columns:
            price = jan_prices.get(ticker, float("nan"))
            sh    = shares.get(ticker, 0.0)
            if not pd.isna(price) and sh > 0 and price > 0:
                mcap[ticker] = price * sh

        top_n = sorted(mcap, key=mcap.get, reverse=True)[:n]
        yearly[year] = set(top_n)

        top5 = ", ".join(top_n[:5])
        print(f"  {year}: {len(top_n)} stocks  top-5: {top5}")

    return yearly


# ── Strategy Simulation ────────────────────────────────────────────────────────

def _calc_size(accumulated_loss: float, premium: float) -> int:
    """Units needed so premium covers accumulated_loss in one month."""
    denom = premium if premium > 0 else FALLBACK_PREMIUM
    return min(MAX_SIZE, max(1, int(np.ceil(accumulated_loss / denom))))


def _get_stock_monthly_data(
    ticker: str,
    prices: pd.Series,
    premiums: dict,
    signal: str = "1m",
) -> pd.DataFrame:
    """
    Scan monthly returns and compute per-unit base metrics — no sizing.

    signal:
      '1m'  — trade when previous 1-month candle was UP  (original rule)
      '6m'  — trade when 6-month return ending prior month was positive
      'none' — always trade regardless of direction

    Returns one row per month: date, trade, prem_frac, return_frac, pnl_pu_frac.
    """
    prices = prices.dropna()
    if len(prices) < 3:
        return pd.DataFrame()

    returns_1m = prices.pct_change().dropna()
    n          = len(returns_1m)
    # prices_arr[i] is the closing price BEFORE returns_1m[i]
    # (returns_1m starts at prices[1], so prices_arr[i] = prices.values[i])
    prices_arr = prices.values
    records    = []
    prev_up_1m = True

    for i in range(n):
        r     = float(returns_1m.iloc[i])
        date  = returns_1m.index[i]
        month = pd.Period(date, "M")

        if signal == "1m":
            trade = prev_up_1m
        elif signal == "6m":
            # 6m return ending at prior month: prices_arr[i] / prices_arr[i-6] - 1
            trade = bool(prices_arr[i] >= prices_arr[i - 6]) if i >= 6 else True
        else:   # 'none'
            trade = True

        if trade:
            prem   = get_premium(premiums, ticker, month, "put")
            pnl_pu = prem + min(r, 0.0)
            records.append({"date": date, "trade": True,
                             "prem_frac": prem, "return_frac": r, "pnl_pu_frac": pnl_pu})
        else:
            records.append({"date": date, "trade": False,
                             "prem_frac": 0.0, "return_frac": r, "pnl_pu_frac": 0.0})
        prev_up_1m = (r >= 0.0)

    return pd.DataFrame(records)


# ── Portfolio Aggregation ──────────────────────────────────────────────────────

def run_portfolio(
    closes: pd.DataFrame,
    premiums: dict,
    signal: str = "1m",
    yearly_universe: "dict[int, set] | None" = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Portfolio-level recovery sizing with point-in-time universe support.

    signal        — momentum filter: '1m', '6m', or 'none'
    yearly_universe — {year: set(tickers)} from build_yearly_universes().
                    If None, all tickers in closes are used every year.

    Each month:
      • Only tickers in yearly_universe[year] are considered.
      • Among those, stocks eligible by the momentum signal trade (sell put).
      • uniform_size = ceil(portfolio_loss% × 100 / (n_active × avg_prem%))
        so one good premium month clears the portfolio deficit.
      • portfolio_episode_pnl resets to 0 when deficit is cleared.
    """
    # Step 1: per-stock base data (direction + per-unit PnL, no sizing)
    base: dict[str, pd.DataFrame] = {}
    for ticker in closes.columns:
        df = _get_stock_monthly_data(ticker, closes[ticker], premiums, signal=signal)
        if not df.empty:
            base[ticker] = df.set_index("date")

    if not base:
        raise RuntimeError("No valid stock simulations produced.")

    all_dates = sorted({d for df in base.values() for d in df.index})

    # Step 2: month-by-month with portfolio-level state
    portfolio_episode_pnl = 0.0   # portfolio % (e.g. -0.70 = -70%)
    portfolio_cum_pnl     = 0.0   # portfolio % cumulative

    stock_cum_pnl: dict[str, float] = {t: 0.0 for t in base}
    all_stock_rows: dict[str, list] = {t: [] for t in base}
    monthly_rows: list              = []

    for date in all_dates:
        # Cumulated loss from last month's close
        portfolio_cumulated_loss = max(0.0, -portfolio_episode_pnl)   # portfolio %
        in_recovery              = portfolio_cumulated_loss > 0.0

        # Point-in-time universe for this year
        year      = date.year
        universe  = yearly_universe.get(year, set(base.keys())) if yearly_universe else set(base.keys())

        # Active stocks: in universe + eligible by momentum signal
        active   = [t for t in base
                    if t in universe
                    and date in base[t].index
                    and bool(base[t].loc[date, "trade"])]
        n_active = len(active)

        # ── Uniform size ──────────────────────────────────────────────────────
        # S × n_active × avg_prem / 100 = portfolio_cumulated_loss
        # S = portfolio_cumulated_loss × 100 / (n_active × avg_prem)
        # (portfolio_cumulated_loss here is a fraction: 0.70 means 70%)
        if in_recovery and n_active > 0:
            avg_prem = float(np.mean([base[t].loc[date, "prem_frac"] for t in active]))
            denom    = avg_prem if avg_prem > 0 else FALLBACK_PREMIUM
            uniform_size = min(MAX_SIZE, max(1, int(np.ceil(
                portfolio_cumulated_loss / (n_active * denom / 100.0)
            ))))
            # Hard cap: total capital deployed ≤ MAX_LEVERAGE × 100%
            # uniform_size × n_active / 100 ≤ MAX_LEVERAGE
            leverage_cap = max(1, int(np.floor(MAX_LEVERAGE * 100 / n_active)))
            uniform_size = min(uniform_size, leverage_cap)
        else:
            uniform_size = 1

        max_hit = uniform_size >= MAX_SIZE

        # ── Compute this month's PnL ──────────────────────────────────────────
        month_portfolio_pnl = 0.0

        for ticker in base:
            if ticker not in universe:
                continue          # outside point-in-time universe this year
            if date not in base[ticker].index:
                continue
            row    = base[ticker].loc[date]
            trade  = bool(row["trade"])
            ret    = float(row["return_frac"])
            prem   = float(row["prem_frac"])
            pnl_pu = float(row["pnl_pu_frac"])
            size   = uniform_size if trade else 0

            # Portfolio % contribution: size × pnl_pu / 100
            contrib = size * pnl_pu / 100.0
            month_portfolio_pnl   += contrib
            stock_cum_pnl[ticker] += contrib

            all_stock_rows[ticker].append({
                "date":                  date,
                "selling":               "put" if trade else "skip",
                "prem_pct":              round(prem   * 100, 4),
                "size":                  size,
                "return_pct":            round(ret    * 100, 4),
                "pnl_pu_pct":            round(pnl_pu * 100, 4),
                "month_pnl_pct":         round(size * pnl_pu * 100, 4),
                "cumulated_loss_pct":    round(portfolio_cumulated_loss * 100, 4),
                "episode_cum_pnl_pct":   round(portfolio_episode_pnl   * 100, 4),
                "total_cum_pnl_pct":     round(stock_cum_pnl[ticker]   * 100, 4),
                "in_recovery":           in_recovery,
                "max_size_hit":          max_hit,
            })

        # ── Update portfolio episode state ────────────────────────────────────
        portfolio_episode_pnl += month_portfolio_pnl
        portfolio_cum_pnl     += month_portfolio_pnl

        if portfolio_episode_pnl >= 0.0:
            portfolio_episode_pnl = 0.0

        monthly_rows.append({
            "date":                         date,
            "monthly_return_pct":           round(month_portfolio_pnl        * 100, 4),
            "cumulative_return_pct":        round(portfolio_cum_pnl          * 100, 4),
            "capital_deployed":             round(uniform_size * n_active / 100.0, 2),
            "num_stocks":                   len(base),
            "num_stocks_trading":           n_active,
            "uniform_size":                 uniform_size,
            "portfolio_cumulated_loss_pct": round(portfolio_cumulated_loss   * 100, 4),
        })

    portfolio_df  = pd.DataFrame(monthly_rows)
    stock_results = {t: pd.DataFrame(rows) for t, rows in all_stock_rows.items() if rows}
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
    print("\n" + "=" * 88)
    print("  MONTHLY PORTFOLIO RETURNS")
    print("=" * 88)
    hdr = (
        f"{'Month':<10}  {'Return%':>8}  {'Cum%':>8}  "
        f"{'CapDeploy':>9}  {'Trading':>7}  {'UniSz':>5}  {'PortLoss%':>9}"
    )
    print(hdr)
    print("-" * 88)
    for _, row in portfolio_df.iterrows():
        date_str = row["date"].strftime("%Y-%m") if hasattr(row["date"], "strftime") else str(row["date"])[:7]
        print(
            f"{date_str:<10}  {row['monthly_return_pct']:>8.3f}  "
            f"{row['cumulative_return_pct']:>8.3f}  "
            f"{row['capital_deployed']:>9.2f}  "
            f"{row['num_stocks_trading']:>7}  "
            f"{row['uniform_size']:>5}  "
            f"{row['portfolio_cumulated_loss_pct']:>9.2f}"
        )
    print("=" * 88)


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
    print(f"  Capital model      : 1/100 per stock; uniform size applied across all active stocks")
    print(f"  Trade rule         : UP candle → sell PUT | DOWN → SKIP (wait)")
    print(f"  Recovery sizing    : portfolio-level; uniform_size = ceil(port_loss% × 100 / (N × avg_prem%))")
    print("=" * 72)
    print(f"\nPORTFOLIO (1/100 capital per stock)")
    print(f"  Final cum return   : {port['final_cum_pnl_pct']:>8.2f} %")
    print(f"  Avg monthly return : {port['avg_monthly_pnl_pct']:>8.4f} %")
    print(f"  Win rate           : {port['win_rate_pct']:>8.1f} %")
    print(f"  Max drawdown       : {port['max_drawdown_pct']:>8.2f} %")
    max_cap  = portfolio_df["capital_deployed"].max()
    max_usiz = portfolio_df["uniform_size"].max()
    print(f"  Max capital deploy : {max_cap:>8.2f}x  (uniform_size × stocks_trading / 100)")
    print(f"  Max uniform size   : {max_usiz:>8}×")
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


# ── Strategy Comparison ────────────────────────────────────────────────────────

def compare_strategies(
    closes: pd.DataFrame,
    premiums: dict,
    yearly_universe: "dict[int, set] | None" = None,
) -> dict:
    """
    Run three momentum-filter variants and print a side-by-side comparison.

    Variants:
      no_filter — always sell PUT (no momentum condition)
      mom_1m    — sell PUT only when previous 1-month candle was UP
      mom_6m    — sell PUT only when 6-month return (ending prior month) > 0

    Returns dict: key → (label, portfolio_df, risk_stats, stock_results)
    """
    configs = [
        ("no_filter", "none", "No momentum filter (always sell PUT)"),
        ("mom_1m",    "1m",   "1M momentum: sell PUT if prev month UP"),
        ("mom_6m",    "6m",   "6M momentum: sell PUT if 6m return > 0"),
    ]

    all_results: dict = {}

    for key, signal, label in configs:
        print(f"\n{'─'*60}")
        print(f"  Running: {label}")
        print(f"{'─'*60}")
        stock_results, portfolio_df = run_portfolio(
            closes, premiums,
            signal=signal,
            yearly_universe=yearly_universe,
        )
        risk = compute_risk_stats(portfolio_df)
        all_results[key] = (label, portfolio_df, risk, stock_results)
        print(f"  → Done. Ann return: {risk['ann_return_pct']:.2f}%  "
              f"Sharpe: {risk['sharpe_4pct_rf']:.3f}  "
              f"MaxDD: {risk['max_drawdown_pct']:.2f}%")

        # Save per-strategy portfolio CSV
        portfolio_df.to_csv(f"portfolio_{key}.csv", index=False)

    # ── Comparison table ──────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("  STRATEGY COMPARISON  —  sell PUT only (3 momentum filters)")
    print("=" * 100)

    col_w = 36
    hdr_fields = [
        ("Strategy",     col_w),
        ("AnnRet%",       8),
        ("AnnVol%",       8),
        ("Sharpe",        7),
        ("Sortino",       7),
        ("MaxDD%",        7),
        ("Calmar",        7),
        ("Win%",          6),
        ("Best%",         7),
        ("Worst%",        7),
    ]
    header = "".join(f"{name:>{w}}" for name, w in hdr_fields)
    print(header)
    print("-" * len(header))

    for key, signal, label in configs:
        _, _, risk, _ = all_results[key]
        row = (
            f"{label:<{col_w}}"
            f"{risk['ann_return_pct']:>{8}.2f}"
            f"{risk['ann_vol_pct']:>{8}.2f}"
            f"{risk['sharpe_4pct_rf']:>{7}.3f}"
            f"{risk['sortino_4pct_rf']:>{7}.3f}"
            f"{risk['max_drawdown_pct']:>{7}.2f}"
            f"{risk['calmar']:>{7}.3f}"
            f"{risk['win_rate_pct']:>{6}.1f}"
            f"{risk['best_month_pct']:>{7}.2f}"
            f"{risk['worst_month_pct']:>{7}.2f}"
        )
        print(row)

    print("=" * 100)

    return all_results


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

    # ── Broader universe: 2024 top-100 + historical large caps ───────────────
    broader = list(dict.fromkeys(TOP100_TICKERS + EXTRA_HISTORICAL))

    # 1. Fetch price data for broader universe
    closes = fetch_monthly_prices(broader, START_DATE, END_DATE)

    # 2. Build point-in-time universes (top-100 per year)
    yearly_universe = build_yearly_universes(closes, n=TOP_N)

    # 3. Run all three strategy variants and print comparison
    all_results = compare_strategies(closes, premiums, yearly_universe=yearly_universe)

    # 4. Detailed output for the 1M-momentum variant (primary strategy)
    label, portfolio_df, risk_stats, stock_results = all_results["mom_1m"]
    print(f"\n{'='*72}")
    print(f"  DETAILED RESULTS — {label}")
    print(f"{'='*72}")
    summary = compute_summary(stock_results, portfolio_df)
    print_summary(summary, portfolio_df)
    print_monthly_table(portfolio_df)
    print_risk_stats(risk_stats)

    # 5. Save outputs (1M strategy)
    print("\nSaving outputs …")
    summary.to_csv("summary.csv", index=False)
    portfolio_df.to_csv("portfolio_pnl.csv", index=False)
    save_history_csv(stock_results)

    # Also save no_filter and 6m stock results
    _, pf_nf, _, sr_nf = all_results["no_filter"]
    save_history_csv.__wrapped__ = None  # no-op attribute
    pd.concat(
        [df.assign(ticker=t) for t, df in sr_nf.items()],
        ignore_index=True,
    ).sort_values(["date", "ticker"]).to_csv("history_no_filter.csv", index=False)

    _, pf_6m, _, sr_6m = all_results["mom_6m"]
    pd.concat(
        [df.assign(ticker=t) for t, df in sr_6m.items()],
        ignore_index=True,
    ).sort_values(["date", "ticker"]).to_csv("history_mom_6m.csv", index=False)

    print("\nOutputs written:")
    print("  summary.csv            — per-stock + portfolio summary (1M momentum)")
    print("  portfolio_pnl.csv      — monthly returns (1M momentum)")
    print("  history.csv            — full trade history (1M momentum)")
    print("  portfolio_no_filter.csv — monthly returns (no filter)")
    print("  portfolio_mom_6m.csv   — monthly returns (6M momentum)")
    print("  history_no_filter.csv  — trade history (no filter)")
    print("  history_mom_6m.csv     — trade history (6M momentum)")


if __name__ == "__main__":
    main()

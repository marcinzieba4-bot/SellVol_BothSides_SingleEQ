#!/usr/bin/env python3
"""Extend the buy_call_1m simulation Jan-2025 .. Feb-2026 (walk-forward).

Old window (Feb 2015 - Dec 2024) is kept exactly as recorded in
history_buy_call_1m.csv. New months are simulated with the same rules:
  signal   : prev-month return >= 0 -> buy 1M ATM call
  pnl_pu   : max(r,0) - prem
  recovery : portfolio-level, size = 2*ceil(loss/(n_active*avg_prem/100)),
             seeded with the Dec-2024 episode state (-1.3575%)
Premium lookup priority (get_premium semantics, post-VIX-cutoff):
  1. ticker's live S3 monthly series (optionsDataCall NVDA, optionsData puts = ATM proxy)
  2. ticker's S3 series average (month beyond series)
  3. PROXY_MAP proxy series (exact month, then avg)
  4. ticker's own average recorded premium from the 2020-09..2024-12 history
  5. FALLBACK 3%
"""
import io, json, os, re, sys
import numpy as np
import pandas as pd
import boto3

SP = "/tmp/claude-0/-home-user-SellVol-BothSides-SingleEQ/f5a4bfe8-ea76-52ba-bd0e-c6ceb8a77cba/scratchpad"
REPO = "/home/user/SellVol_BothSides_SingleEQ"
TARGET_DTE, ASSUMED_DTE, FALLBACK, MAX_SIZE = 30, 25, 0.03, 5000
NEW_MONTHS = pd.period_range("2025-01", "2026-02", freq="M")

sys.path.insert(0, REPO)
os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ["AWS_Key"])

# PROXY_MAP from strategy.py (import would trigger yfinance; parse instead)
src = open(f"{REPO}/strategy.py").read()
proxy_src = src[src.find("PROXY_MAP = {"):]
proxy_src = proxy_src[:proxy_src.find("\n}") + 2]
PROXY_MAP = eval(proxy_src[len("PROXY_MAP = "):])

s3 = boto3.client("s3", region_name="eu-north-1",
                  aws_access_key_id=os.environ["AWS_Key"],
                  aws_secret_access_key=os.environ["AWS_Pass"])

def load_summary(prefix, t):
    for key in (f"{prefix}/{t}/{t}/{t}_history_summary.csv",
                f"{prefix}/{t}/{t}_history_summary.csv"):
        try:
            o = s3.get_object(Bucket="s3bucketmz", Key=key)
        except Exception:
            continue
        df = pd.read_csv(io.BytesIO(o["Body"].read()))
        df["observation_date"] = pd.to_datetime(df["observation_date"])
        df["prem_frac"] = df["entry_premium"] / df["stock_price"]
        raw = pd.to_numeric(df["dte_at_obs"], errors="coerce")
        df["_dte"] = raw.where(raw > 0, ASSUMED_DTE).fillna(ASSUMED_DTE)
        df["prem_frac"] *= (1 + 0.4 * (TARGET_DTE / df["_dte"] - 1))
        df["month"] = df["observation_date"].dt.to_period("M")
        m = df.sort_values("observation_date").groupby("month")["prem_frac"].last()
        return {"monthly": m.to_dict(), "avg": float(df["prem_frac"].mean())}
    return None

# live S3 series: NVDA call takes precedence, put summaries for the rest
live = {}
res = s3.list_objects_v2(Bucket="s3bucketmz", Prefix="optionsData/", Delimiter="/")
put_ticks = [p["Prefix"].split("/")[1] for p in res.get("CommonPrefixes", [])]
for t in put_ticks:
    r = load_summary("optionsData", t)
    if r: live[t] = r
nv = load_summary("optionsDataCall", "NVDA")
if nv: live["NVDA"] = nv
print("live premium series:", sorted(live))

# recorded per-ticker average premium (post-2020-09 real-data window)
hist = pd.read_csv(f"{REPO}/history_buy_call_1m.csv", parse_dates=["date"])
rec_avg = (hist[(hist["side"] == "buy_call") & (hist["date"] >= "2020-09-01")]
           .groupby("ticker")["call_prem_pct"].mean() / 100).to_dict()

src_count = {"s3_exact": 0, "s3_avg": 0, "proxy": 0, "hist_avg": 0, "fallback": 0}
def premium(t, m):
    if t in live:
        if m in live[t]["monthly"]:
            src_count["s3_exact"] += 1; return live[t]["monthly"][m]
        src_count["s3_avg"] += 1; return live[t]["avg"]
    p = PROXY_MAP.get(t)
    if p and p in live:
        src_count["proxy"] += 1
        return live[p]["monthly"].get(m, live[p]["avg"])
    if t in rec_avg:
        src_count["hist_avg"] += 1; return rec_avg[t]
    src_count["fallback"] += 1; return FALLBACK

# prices / returns
prices = json.load(open(f"{SP}/prices_ext.json"))
rets = {}   # (ticker, period) -> monthly return
for t, series in prices.items():
    s = pd.Series(series); s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    s = s.sort_index()
    r = s.pct_change().dropna()
    for m, v in r.items(): rets[(t, m)] = float(v)

u = json.load(open(f"{SP}/universes.json"))
UNIV = {2025: set(u["u25"]) - {"FI", "MMC"}, 2026: set(u["u26"]) - {"FI", "MMC"}}

# continuity check: fresh Dec-2024 returns vs recorded
old_dec = hist[hist["date"] == "2024-12-01"].set_index("ticker")["return_pct"] / 100
both = [t for t in old_dec.index if (t, pd.Period("2024-12")) in rets]
flips = [t for t in both if (old_dec[t] >= 0) != (rets[(t, pd.Period("2024-12"))] >= 0)]
diffs = [abs(old_dec[t] - rets[(t, pd.Period("2024-12"))]) for t in both]
print(f"continuity: {len(both)} tickers, median |diff| {np.median(diffs)*100:.3f}pp, sign flips: {flips}")

# walk-forward simulation
episode = -0.013575          # Dec-2024 episode P&L (fraction)
rows, monthly = [], []
for m in NEW_MONTHS:
    universe = UNIV[m.year]
    loss = max(0.0, -episode)
    in_rec = loss > 0
    active = [t for t in universe
              if (t, m) in rets and (t, m - 1) in rets and rets[(t, m - 1)] >= 0]
    if in_rec and active:
        avg_prem = float(np.mean([premium(t, m) for t in active]))
        denom = avg_prem if avg_prem > 0 else FALLBACK
        size = min(MAX_SIZE, 2 * max(1, int(np.ceil(loss / (len(active) * denom / 100.0)))))
    else:
        size = 1
    month_pnl = 0.0
    for t in sorted(universe):
        if (t, m) not in rets or (t, m - 1) not in rets:
            continue
        r = rets[(t, m)]
        bullish = rets[(t, m - 1)] >= 0
        if bullish:
            prem = premium(t, m)
            pnl_pu = max(r, 0.0) - prem
            sz = size
            side = "buy_call"
        else:
            prem, pnl_pu, sz, side = 0.0, 0.0, 0, "skip"
        month_pnl += sz * pnl_pu / 100.0
        rows.append({"date": m.to_timestamp(), "ticker": t, "side": side,
                     "call_prem_pct": round(prem * 100, 4), "size": sz,
                     "return_pct": round(r * 100, 4),
                     "pnl_pu_pct": round(pnl_pu * 100, 4),
                     "pnl_contribution_pct": round(sz * pnl_pu / 100, 6),
                     "in_recovery": in_rec})
    episode += month_pnl
    if episode >= 0: episode = 0.0
    monthly.append({"date": m.to_timestamp(), "monthly_return_pct": round(month_pnl * 100, 4),
                    "num_stocks_trading": len(active), "uniform_size": size,
                    "portfolio_cumulated_loss_pct": round(loss * 100, 4)})
    print(f"{m}  ret {month_pnl*100:+7.2f}%  bets {len(active):3d}  size {size:3d}"
          f"  loss@start {loss*100:6.2f}%")

print("premium sources:", src_count)
ext = pd.DataFrame(rows)
ext.to_csv(f"{SP}/history_ext_2025on.csv", index=False)
pd.DataFrame(monthly).to_csv(f"{SP}/portfolio_ext_2025on.csv", index=False)
print("saved extension:", len(ext), "rows,", len(monthly), "months")

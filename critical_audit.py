#!/usr/bin/env python3
"""Adversarial audit of InsideSPX Momentum + short-SPY-call overlay test."""
import json
import numpy as np
import pandas as pd
from scipy import stats as sps

SP = "/tmp/claude-0/-home-user-SellVol-BothSides-SingleEQ/f5a4bfe8-ea76-52ba-bd0e-c6ceb8a77cba/scratchpad"
REPO = "/home/user/SellVol_BothSides_SingleEQ"
rng = np.random.default_rng(7)

h = pd.read_csv(f"{REPO}/history_buy_call_1m_extended.csv", parse_dates=["date"]).reset_index(drop=True)
h["ym"] = h["date"].dt.to_period("M")
tr = h[h["side"] == "buy_call"]
g = tr.groupby("ym")
pnl1 = g["pnl_pu_pct"].sum() / 100 / 100    # 1x option P&L, fraction of capital
capin = g["call_prem_pct"].sum() / 100      # premium outlay, % of capital
nact = g.size()
months = pnl1.index

ff = pd.read_csv(f"{SP}/fedfunds2.csv", parse_dates=["observation_date"])
ff["ym"] = ff["observation_date"].dt.to_period("M")
ffr = (ff.set_index("ym")["FEDFUNDS"] / 100 / 12).reindex(months)

spy_raw = json.load(open(f"{SP}/spy_vix.json"))["SPY"]
spy = pd.Series({r["date"]: r["close"] for r in spy_raw})
spy.index = pd.PeriodIndex(pd.to_datetime(spy.index), freq="M")
spy_ret = spy.sort_index().pct_change().reindex(months)
assert not spy_ret.isna().any()

vix = pd.read_csv(f"{SP}/vixcls.csv", parse_dates=["observation_date"]).dropna()
vix["ym"] = vix["observation_date"].dt.to_period("M")
vix_eom = vix.groupby("ym")["VIXCLS"].last()          # month-end VIX
vix_prev = vix_eom.shift(1).reindex(months) / 100     # IV known at month start

def ann_stats(r, label):
    r = np.asarray(r, float)
    n = len(r)
    ann = (1 + r).prod() ** (12 / n) - 1
    vol = r.std(ddof=1) * np.sqrt(12)
    cum = (1 + r).cumprod()
    dd = ((cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum)).min()
    print(f"  {label:<34} total {((1+r).prod()-1)*100:>8.1f}%  ann {ann*100:>6.2f}%  "
          f"vol {vol*100:>5.2f}%  sharpe(0RF) {ann/vol:>5.2f}  maxDD {dd*100:>6.1f}%  "
          f"win {(r>0).mean()*100:.0f}%")
    return dict(ann=ann, vol=vol, dd=dd)

print("=" * 100)
print("1. WHAT ARE YOU ACTUALLY EARNING?  (133 months, Feb 2015 - Feb 2026)")
opt = pnl1.values                       # option P&L only, no cash yield
cash = (ffr * (1 - capin / 100)).values
r1 = opt + cash
ann_stats(r1, "1x incl. Fed-Funds cash yield")
ann_stats(opt, "1x OPTION P&L ONLY (the strategy)")
ann_stats(cash, "cash yield alone")
ann_stats(spy_ret.values, "SPY buy & hold")

print("\n2. BETA / ALPHA vs SPY  (option P&L only)")
x = spy_ret.values
X = np.column_stack([np.ones_like(x), x])
b, res, *_ = np.linalg.lstsq(X, opt, rcond=None)
e = opt - X @ b
se = np.sqrt(np.sum(e**2) / (len(x) - 2) / np.sum((x - x.mean())**2))
sea = np.sqrt(np.sum(e**2) / (len(x) - 2) * (1/len(x) + x.mean()**2 / np.sum((x - x.mean())**2)))
print(f"  beta {b[1]:.3f} (t={b[1]/se:.1f})   alpha {b[0]*12*100:+.2f}%/yr (t={b[0]/sea:.2f})   "
      f"corr {np.corrcoef(opt, x)[0,1]:.2f}")
xp = np.maximum(x, 0)
X2 = np.column_stack([np.ones_like(x), xp])
b2, *_ = np.linalg.lstsq(X2, opt, rcond=None)
e2 = opt - X2 @ b2
sea2 = np.sqrt(np.sum(e2**2)/(len(x)-2) * (1/len(x) + xp.mean()**2/np.sum((xp-xp.mean())**2)))
print(f"  vs max(SPY,0): slope {b2[1]:.3f}, alpha {b2[0]*12*100:+.2f}%/yr (t={b2[0]/sea2:.2f})"
      f"   <- is there anything beyond owning upside beta?")

print("\n3. CONCENTRATION: how much depends on a few months?")
srt = np.sort(opt)[::-1]
tot = opt.sum()
print(f"  additive option P&L total: {tot*100:.1f}%  |  top-3 months: {srt[:3].sum()*100:.1f}%"
      f" ({srt[:3].sum()/tot*100:.0f}%)  top-10: {srt[:10].sum()*100:.1f}% ({srt[:10].sum()/tot*100:.0f}%)")
mask = np.argsort(opt)[::-1][3:]
ann_stats(opt[np.sort(mask)], "option P&L excluding top 3 months")

print("\n4. PROXY-PREMIUM ERA vs REAL-DATA ERA (option P&L only)")
pre = months < pd.Period("2020-09")
ann_stats(opt[pre], f"Feb15-Aug20  PROXY premiums ({pre.sum()} mo)")
ann_stats(opt[~pre], f"Sep20-Feb26  real-ish data ({(~pre).sum()} mo)")

print("\n5. PREMIUM REALISM")
iv = tr["call_prem_pct"].values / 100 / (0.4 * np.sqrt(1 / 12))
print(f"  implied vol backed out of paid premiums: median {np.median(iv)*100:.0f}%,"
      f"  10th pct {np.percentile(iv,10)*100:.0f}%,  90th {np.percentile(iv,90)*100:.0f}%")
print(f"  share of trades priced below 15% implied vol: {(iv<0.15).mean()*100:.0f}%"
      f"   (S&P-100 single-stock 1M IV realistically 18-45%)")
carry = ((ffr - 0.016 / 12).clip(lower=0) * (nact / 100)).values
print(f"  put-premium-as-call-premium omits carry (r - div): "
      f"~{carry.sum()*100:.1f}% cumulative (~{carry.mean()*12*100:.2f}%/yr) overstated at 1x")

print("\n6. DOES THE MOMENTUM FILTER ADD ANYTHING?")
prem_avg = tr.groupby("ticker")["call_prem_pct"].mean() / 100
hh = h[h["ticker"].isin(prem_avg.index)].copy()
hh["pa"] = hh["ticker"].map(prem_avg)
hh["hyp_pnl"] = np.maximum(hh["return_pct"] / 100, 0) - hh["pa"]
pos = hh[hh["side"] == "buy_call"]["hyp_pnl"]
neg = hh[hh["side"] == "skip"]["hyp_pnl"]
t, p = sps.ttest_ind(pos, neg, equal_var=False)
print(f"  signal-positive names: mean {pos.mean()*100:+.2f}%/trade (n={len(pos)})")
print(f"  signal-NEGATIVE names: mean {neg.mean()*100:+.2f}%/trade (n={len(neg)})"
      f"   diff t={t:.2f} p={p:.3f}")

print("\n7. RECOVERY-SIZING RUIN TEST (10,000 bootstrap resamples of the 133 months)")
P = np.column_stack([pnl1.values, capin.values / 100])   # fractions
NB, NM = 10000, 133
ruin = big_dd = cap_over = 0
finals = np.empty(NB)
for i in range(NB):
    idx = rng.integers(0, NM, NM)
    loss = 0.0
    wealth = 0.0
    peak = 0.0
    worst_cap = 0.0
    dead = False
    for pnl_m, cap_m in P[idx]:
        size = 1 if loss <= 0 else min(5000, 2 * max(1, int(np.ceil(loss / cap_m))))
        worst_cap = max(worst_cap, size * cap_m)
        r = size * pnl_m
        wealth += r
        loss = max(0.0, loss - r) if r > 0 else loss + (-r)
        # episode bookkeeping identical to strategy: loss = max(0, -(episode))
        peak = max(peak, wealth)
        if wealth - peak < -1.0 or wealth < -1.0:
            dead = True
    finals[i] = wealth
    if dead: ruin += 1
    if worst_cap > 100: cap_over += 1
print(f"  P(premium outlay ever exceeds 100% of capital): {cap_over/NB*100:.1f}%")
print(f"  P(equity ever down >100% of starting capital):  {ruin/NB*100:.1f}%")
print(f"  final additive P&L: median {np.median(finals)*100:.0f}%,  5th pct {np.percentile(finals,5)*100:.0f}%,"
      f"  1st pct {np.percentile(finals,1)*100:.0f}%")

print("\n" + "=" * 100)
print("8. SHORT SPY 1M CALLS OVERLAY  (long 1x momentum stock calls + short SPY calls, notional-matched)")
sig = np.sqrt(1 / 12)
prem_atm = 0.4 * vix_prev.values * sig                       # ATM approx, IV = VIX
from math import erf
N = lambda z: 0.5 * (1 + erf(z / np.sqrt(2)))
Nv = np.vectorize(N)
sT = vix_prev.values * sig
kos = np.exp(0.5244 * sT + sT**2 / 2)                        # 30-delta strike / spot
d1 = np.full_like(sT, -0.5244)
d2 = d1 - sT
prem_30 = Nv(d1) - kos * Nv(d2)                              # 30d call premium / spot
rs = spy_ret.values
short_atm = prem_atm - np.maximum(rs, 0)                     # per unit of SPY notional
short_30 = prem_30 - np.maximum((1 + rs) - kos, 0)
w = (nact / 100).values                                      # match long-leg notional
print(f"  SPY ATM prem: mean {prem_atm.mean()*100:.2f}%/mo   30-delta prem: mean {prem_30.mean()*100:.2f}%/mo")
ann_stats(w * short_atm, "short SPY ATM alone (scaled)")
ann_stats(opt, "long stock calls alone (1x)")
ov_atm = opt + w * short_atm
ov_30 = opt + w * short_30
ann_stats(ov_atm, "OVERLAY: long calls + short SPY ATM")
ann_stats(ov_30, "OVERLAY: long calls + short SPY 30d")
for nm, ov in [("ATM", ov_atm), ("30d", ov_30)]:
    bo, *_ = np.linalg.lstsq(X, ov, rcond=None)
    eo = ov - X @ bo
    seao = np.sqrt(np.sum(eo**2)/(len(x)-2)*(1/len(x)+x.mean()**2/np.sum((x-x.mean())**2)))
    to = bo[0] / seao
    print(f"  overlay {nm}: beta {bo[1]:+.2f}  alpha {bo[0]*12*100:+.2f}%/yr (t={to:.2f})"
          f"  corr(SPY) {np.corrcoef(ov, x)[0,1]:+.2f}")
ann_stats(ov_atm + cash, "overlay ATM incl. cash yield")

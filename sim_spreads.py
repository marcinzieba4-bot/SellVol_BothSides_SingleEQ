#!/usr/bin/env python3
"""
Weekly simulation of a defined-risk book, 2015-02 → 2024-12:

  A. single-name put credit spreads: short 30-delta / long 10-delta, 28 DTE,
     equal-weight over the point-in-time top-100 universe, 1× equity notional
  B. SPY put credit spread: short 30-delta / long 2-delta, 28 DTE, L× equity notional
  C. B with a weekly SPY-share delta hedge
  Rotating half-book: a new cohort every 2 weeks, each half the target notional.

Strikes and premiums are Black-Scholes (r = 0). Single-name IV comes from the
backtest's ATM premiums (history.csv); SPY IV = VIX at entry and at each hedge.
Costs: single-name 15 % of credit + $2.20/spread; SPY 5 % of credit + $2.20;
hedge 1 bp of traded value. No integer-contract rounding (see note in output).
"""
from __future__ import annotations
import math, sys
import numpy as np, pandas as pd

T_DAYS = 28; DT = T_DAYS / 365
COST_SN, COST_SPY, COMM = 0.15, 0.05, 2.20


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def put(S, K, sig, T):
    if T <= 0: return max(K - S, 0.0)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    return K * N(-d2) - S * N(-d1)


def put_delta(S, K, sig, T):
    if T <= 0: return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T)); return -N(-d1)


def strike_for_delta(S, sig, T, delta):        # put with |delta| = delta
    z = -math.sqrt(2) * _erfinv(2 * (1 - delta) - 1)      # d1 such that N(-d1)=delta
    d1 = -z
    return S * math.exp(-(d1 * sig * math.sqrt(T)) + 0.5 * sig * sig * T)


def _erfinv(y):
    a = 0.147; ln = math.log(1 - y * y); t = 2 / (math.pi * a) + ln / 2
    x = math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), y)
    for _ in range(3):                                   # Newton polish
        x -= (math.erf(x) - y) / (2 / math.sqrt(math.pi) * math.exp(-x * x))
    return x


def load_weekly(tickers):
    import yfinance as yf
    try:
        w = pd.read_csv("weekly_closes.csv", index_col=0, parse_dates=True)
        if set(tickers + ["SPY", "^VIX"]) <= set(w.columns): return w
    except FileNotFoundError: pass
    raw = yf.download(tickers + ["SPY", "^VIX"], start="2014-12-01", end="2025-01-10", interval="1wk",
                      auto_adjust=False, progress=False)["Close"]
    raw.to_csv("weekly_closes.csv"); return raw


def main():
    hist = pd.read_csv("history.csv", parse_dates=["date"])
    tickers = sorted(hist.ticker.unique())
    W = load_weekly(tickers).sort_index()
    W = W[W.index >= "2015-01-01"]
    weeks = list(W.index)
    # universe per year from history, IV per ticker-month from ATM premium
    uni = hist.groupby(hist.date.dt.year).ticker.apply(set).to_dict()
    tr = hist[hist.prem_pct > 0].copy(); tr["m"] = tr.date.dt.to_period("M")
    tr["iv"] = tr.prem_pct / 100 / (0.3989 * math.sqrt(30 / 365))
    iv_tm = tr.set_index(["ticker", "m"]).iv.to_dict()
    iv_t = tr.groupby("ticker").iv.mean().to_dict(); iv_all = tr.iv.mean()
    mfac = (tr.groupby("m").iv.mean() / iv_all).to_dict()

    def iv_for(t, d):
        m = pd.Period(d, "M")
        if (t, m) in iv_tm: return iv_tm[(t, m)]
        return iv_t.get(t, iv_all) * mfac.get(m, 1.0)

    # ---- cohort results per entry week (as fraction of cohort notional) ----
    sn_ret = {}; spy_ret = {}; spy_hedged = {}; spy_delta0 = {}
    for i, d in enumerate(weeks[:-4]):
        if i % 2: continue                              # new cohort every 2 weeks
        dexp = weeks[i + 4]
        # A. single names
        names = [t for t in uni.get(d.year, set()) if t in W.columns and np.isfinite(W.at[d, t]) and np.isfinite(W.at[dexp, t])]
        rets = []
        for t in names:
            S0, ST, sig = W.at[d, t], W.at[dexp, t], iv_for(t, d)
            K1, K2 = strike_for_delta(S0, sig, DT, .30), strike_for_delta(S0, sig, DT, .10)
            credit = put(S0, K1, sig, DT) - put(S0, K2, sig, DT)
            pnl = credit * (1 - COST_SN) - COMM / 100 - (max(K1 - ST, 0) - max(K2 - ST, 0))
            rets.append(pnl / S0)
        sn_ret[d] = float(np.mean(rets)) if rets else 0.0
        # B/C. SPY
        S0, ST, sig = W.at[d, "SPY"], W.at[dexp, "SPY"], W.at[d, "^VIX"] / 100
        K1, K2 = strike_for_delta(S0, sig, DT, .30), strike_for_delta(S0, sig, DT, .02)
        credit = put(S0, K1, sig, DT) - put(S0, K2, sig, DT)
        settle = max(K1 - ST, 0) - max(K2 - ST, 0)
        base = credit * (1 - COST_SPY) - COMM / 100 - settle
        spy_ret[d] = base / S0
        hedge = 0.0
        for k in range(4):                               # weekly re-hedge: short D shares per spread
            dk, dk1 = weeks[i + k], weeks[i + k + 1]
            Sk, sk = W.at[dk, "SPY"], W.at[dk, "^VIX"] / 100
            Tk = (4 - k) * 7 / 365
            D = -put_delta(Sk, K1, sk, Tk) + put_delta(Sk, K2, sk, Tk)   # net delta of short spread (>0)
            hedge += -D * (W.at[dk1, "SPY"] - Sk) - 1e-4 * D * Sk
            if k == 0: spy_delta0[d] = D
        spy_hedged[d] = (base + hedge) / S0

    # ---- book: compound weekly on equity ----
    def run(sn_mult, spy_mult, hedged):
        eq = 1.0; curve = []
        src = spy_hedged if hedged else spy_ret
        for i, d in enumerate(weeks[:-4]):
            if i % 2: continue
            dexp = weeks[i + 4]
            pnl = eq * (sn_mult * 0.5 * sn_ret[d] + spy_mult * 0.5 * src[d])   # each cohort = half the target
            eq += pnl; curve.append((dexp, eq))
        c = pd.Series(dict(curve)).sort_index()
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        dd = (c / c.cummax() - 1).min()
        worst4 = (c / c.shift(2) - 1).min()               # worst rolling 4-week outcome
        return dict(final=c.iloc[-1], cagr=c.iloc[-1] ** (1 / yrs) - 1, maxdd=dd, worst4w=worst4,
                    y2020=c[c.index <= "2020-04-30"].iloc[-1] / c[c.index <= "2020-02-07"].iloc[-1] - 1,
                    y2022=c[c.index <= "2022-12-31"].iloc[-1] / c[c.index <= "2022-01-07"].iloc[-1] - 1)

    rows = [("A  single-name 30/10 spreads, 1× notional", run(1, 0, False)),
            ("A  same at 2× notional", run(2, 0, False)),
            ("B  SPY 30/2 spread 3×, unhedged", run(0, 3, False)),
            ("B  SPY 30/2 spread 5×, unhedged", run(0, 5, False)),
            ("C  SPY 30/2 spread 3×, weekly share hedge", run(0, 3, True)),
            ("C  SPY 30/2 spread 4×, weekly share hedge", run(0, 4, True)),
            ("C  SPY 30/2 spread 5×, weekly share hedge", run(0, 5, True)),
            ("A+B  single names 1× + SPY 4× unhedged", run(1, 4, False)),
            ("A+C  single names 1× + SPY 4× hedged", run(1, 4, True))]
    df = pd.DataFrame([dict(book=k, **v) for k, v in rows])
    pd.set_option("display.width", 220)
    print(df.to_string(index=False, formatters={c: "{:.1%}".format for c in ["cagr", "maxdd", "worst4w", "y2020", "y2022"]} | {"final": "{:.2f}x".format}))
    sr = pd.Series(spy_ret); sh = pd.Series(spy_hedged); sn = pd.Series(sn_ret)
    print(f"\nper-cohort stats (% of cohort notional, 28 d): single-name mean {sn.mean()*100:.3f}%  win {(sn>0).mean():.0%}  worst {sn.min()*100:.2f}%")
    print(f"SPY unhedged mean {sr.mean()*100:.3f}%  win {(sr>0).mean():.0%}  worst {sr.min()*100:.2f}%   | hedged mean {sh.mean()*100:.3f}%  win {(sh>0).mean():.0%}  worst {sh.min()*100:.2f}%   entry delta ≈ {np.mean(list(spy_delta0.values())):.2f}")
    S = W["SPY"].iloc[-1]; print(f"\nSPY last close in data: {S:.0f} → one spread = ${S*100:,.0f} notional; at $50k, 4× = {4*50000/(S*100):.1f} spreads total, {2*50000/(S*100):.1f} per cohort")
    df.to_csv("sim_spreads.csv", index=False)


if __name__ == "__main__":
    main()

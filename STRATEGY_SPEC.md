# InsideSPX Dispersion — strategy specification (derived from the audit)

One line: **buy 1-month ATM calls on every top-100 SPX name, sell 1-month ATM SPY
calls against the whole book, notional-matched, fixed 1x size, cash in T-bills.**
It is a call-implemented dispersion trade: the average single stock out-runs the
index on the upside (correlation < 1), and index upside is what you sell.

## Evidence behind each design decision (see CRITICAL_ANALYSIS.md / critical_audit.py)
- Unhedged long calls = 0.22 SPY beta, negative alpha vs max(SPY,0) → hedge is mandatory.
- Momentum filter selects the WORSE half (reversal, t=7.9) → no filter; breadth is the edge.
  Hedged variants: momentum ann +5.6% / Sharpe 2.5; ALL NAMES +11.9% / Sharpe 3.3
  (still +8.7% / 2.5 with post-down-name premiums stressed +25%); reversal-only dies
  under the same stress (+2.9%).
- Recovery sizing: 16% bootstrap probability of needing >100% of capital → fixed 1x only.
- Hedge results (133 mo): beta ~0.0, vol ~2-4%, maxDD -1.7% (ATM) with alpha t≈7-10.

## Rules
1. **Universe**: top-100 S&P 500 members by market cap, point-in-time, refreshed yearly.
   Drop names without listed 1-month options or with >2% of premium in bid-ask spread.
2. **Long leg**: first trading day each month, buy 1 unit (1% of capital notional) of
   ~30-DTE ATM calls on EVERY universe name with data. No signal filter.
3. **Short leg**: same day, sell SPY ~30-DTE ATM calls with notional = number of long
   names × 1% of capital (i.e., matched to the long leg). Alternative: 30-delta SPY
   calls keep ~0.14 beta and add ~2-3%/yr - a risk preference, not an edge difference.
4. **Hold to expiry**, settle, re-establish. No intramonth adjustments.
5. **Sizing**: FIXED. Premium outlay ~2-3% of capital/month long, ~2% received short.
   No loss-recovery scaling of any kind. Optional leverage: scale both legs together,
   hard cap so worst historical month (about -2% at 1x, hedged) x leverage <= risk budget.
6. **Cash**: everything not posted as premium/margin in T-bills / money market.
7. **Costs**: cross at mid +/- limit; skip any name whose spread eats >15% of its premium.

## Honest expectations (after carry ~0.6%/yr and costs ~0.7-1%/yr at 1x)
Option P&L ~4-7%/yr over cash at ~3.5% vol, Sharpe ~1.2-1.8, maxDD low single digits,
market-neutral. NOT the backtest's 11.9%: single-stock premiums in the dataset are
cheap (median implied 19%), so haircut expectations, not the construction.

## Failure modes / kill criteria
- Implied correlation collapse (single-name IV rich vs index IV): the entry spread you
  pay widens; monitor CBOE implied correlation; stand down when 1M implied corr < ~15.
- Melt-up led by index concentration (a few mega-caps = the index): short SPY leg loses
  what long legs on those same names make; residual is small by construction but the
  top-10-weight concentration of SPX today is the main structural risk to watch.
- Both legs bleed in low-vol grind: theta on 100 longs vs 1 short; acceptable while
  single-name premium <= ~2x index premium per unit notional; re-check quarterly.
- Kill: trailing-24-month hedged option P&L < 0, or realized beta drifts > |0.15|.

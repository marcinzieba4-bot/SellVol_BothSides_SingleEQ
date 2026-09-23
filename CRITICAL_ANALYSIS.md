# InsideSPX Momentum — adversarial audit (Sep 2026)

Run `python3 critical_audit.py` (needs scratchpad data: fedfunds2.csv, spy_vix.json,
vixcls.csv — refetchable from FRED / the yfinance-data-fetcher Lambda).
Window: Feb 2015 – Feb 2026, 133 months, extended history.

## Does it really earn money? Mostly no — it earns beta, cash yield, and data optimism.

1. **Decomposition (1×):** +8.0%/yr = 2.0% Fed-Funds cash yield + 5.9% option P&L
   (Sharpe 1.33 stand-alone). SPY buy-and-hold over the same window: +13.7%/yr.
2. **It is upside beta, not alpha.** Option P&L has beta 0.22 to SPY (corr 0.75).
   CAPM alpha +2.7%/yr (t=2.97), but regressed on max(SPY,0) — i.e., what a plain
   SPY call position delivers — alpha is NEGATIVE (−2.6%/yr, t=−1.9). A 30% SPY /
   70% cash portfolio earns ~7.5%/yr with similar drawdown to the 1× strategy's 8.0%.
3. **The momentum filter destroys value.** Signal-NEGATIVE names returned MORE the
   next month than signal-positive names (+1.66% vs +1.03% raw; call payoff 4.04%
   vs 3.28%, t=7.9): classic 1-month reversal. The filter systematically discards
   the better half of the universe. (Real post-loss IV is higher, which would eat
   some of the reversal, but the raw-return gap stands.)
4. **The proxy-premium era carries the backtest.** Feb15–Aug20 (synthetic VIX-scaled
   premiums): option P&L +8.1%/yr, Sharpe 1.97. Sep20–Feb26 (real-ish data):
   +3.65%/yr, Sharpe 0.79. The half with market prices earns less than half.
5. **Premiums look too cheap.** Median implied vol backed out of premiums paid: 19%;
   34% of trades below 15% IV (realistic S&P-100 1M ATM IV: 18–45%). Put premiums
   are used as call premiums, omitting carry (r − div): ~0.6%/yr overstatement at 1×.
   No transaction costs: ~58 single-stock option trades/month ≈ another ~0.5–1%/yr.
   → honest 1× option-only edge ≈ **~2%/yr over cash**, and it is mostly upside beta.
6. **Concentration:** top-10 months = 47% of all option P&L; top-3 = 18%.
7. **Recovery sizing is a martingale.** Bootstrap (10k × 133mo, iid — which
   UNDERSTATES clustered drawdowns): 16% of paths need premium outlay >100% of
   capital at some point (median path peaks at 36%, 99th pct 787%); 3% lose more
   than the starting capital. The +2,341% headline is one path of a rule whose tail
   is ruin; April 2025 already ran it to size 126 and 41% of capital in premiums.

## Short SPY 1M calls overlay (requested test)

Long 1× momentum stock calls + short SPY calls, notional-matched to the long leg.
SPY has no options data in the bucket, so SPY premiums are priced off VIX
(ATM ≈ 0.4·(VIX/100)·√(1/12); VIX is the 30-day SPX IV — realistic, note this is a
*stricter* standard than the long leg's proxy premiums).

Option P&L only, 133 months:

| | ann | vol | Sharpe (0RF) | maxDD | beta | alpha (t) |
|---|---|---|---|---|---|---|
| long calls alone (1×) | +5.9% | 4.4% | 1.33 | −8.0% | 0.22 | +2.7%/yr (3.0) |
| short SPY ATM alone | −0.4% | 4.0% | −0.11 | −12.0% | | |
| **overlay ATM** | **+5.6%** | **2.3%** | **2.47** | **−1.7%** | **0.02** | **+5.3%/yr (7.5)** |
| overlay 30-delta | +8.4% | 3.5% | 2.38 | −4.1% | 0.14 | +6.1%/yr (7.0) |

Real-data era only (Sep20–Feb26): overlay ATM +3.9%/yr at 2.3% vol (Sharpe 1.69,
maxDD −1.7%); 30-delta +6.4%/yr, Sharpe 1.76. The hedge is the one genuinely
interesting result: it converts leveraged upside beta into a market-neutral
dispersion/relative-momentum book — sell index upside, own single-stock upside.
Same caveats apply (long-leg premium optimism, ~0.6%/yr carry, costs, short-call
margin): a realistic expectation is ~2–3%/yr over cash at ~2.3% vol, not the
headline. The ATM version is the cleaner hedge; 30-delta keeps residual beta.

## Both-sides dispersion with bid/ask spreads (real quotes, Sep 2020 - Feb 2026)

S3 today holds option files for only 14 tickers (13 puts + NVDA calls; the other
~28 optionsDataCall directories are empty placeholders; all prices are 'last'
prints, no mid/bid/ask columns). Treating last as mid, buying single-name
straddles at mid*(1+h), selling SPY straddles at mid*(1-0.5%), scaled to full
deployment incl. cash at FFR:

| h (half-spread) | ann | Sharpe | maxDD | Calmar |
|---|---|---|---|---|
| 0%   | +17.0% | 2.55 | -3.7% | 4.55 |
| 2.5% | +14.5% | 2.16 | -4.0% | 3.60 |
| 5%   | +12.2% | 1.82 | -4.3% | 2.84 |
| 7.5% | +10.1% | 1.49 | -4.8% | 2.11 |

Each 2.5pp of half-spread costs ~2.3%/yr. Window contains no true crash
(model estimate for 2008-10: about -5% in one month at full deployment x scale).

## Variant tests on real VolVue IVs (2007-2026, hedged vs SPY, option P&L)

| variant | ann | Sharpe | maxDD | Calmar | alpha t | Sep20+ ann |
|---|---|---|---|---|---|---|
| calls-only ATM, all names | +1.94% | 0.68 | -15.0% | 0.13 | 3.2 | -0.2% |
| calls+puts ATM, all names | +0.64% | 0.14 | -30.1% | 0.02 | 0.8 | -0.7% |
| calls-only ATM, momentum | +1.07% | 0.57 | -9.5% | 0.11 | 2.7 | +0.2% |
| calls-only 40-delta | +2.14% | 0.79 | -10.5% | 0.20 | 3.5 | +0.5% |
| calls-only 30-delta | +2.69% | 1.08 | -7.1% | 0.38 | 4.2 | +2.0% |
| calls-only 20-delta | +2.79% | 1.36 | -4.8% | 0.59 | 5.0 | +2.8% |
| 30-delta strangle | +1.89% | 0.54 | -17.2% | 0.11 | 2.2 | +1.6% |
| 30-delta calls, momentum | +1.63% | 1.03 | -3.5% | 0.47 | 4.0 | +1.1% |

Findings: (1) the put wing destroys value - calls-only dominates calls+puts;
(2) the momentum filter still subtracts vs all names (breadth wins);
(3) going OTM helps monotonically (20-delta best, and the only variant clearly
positive in the recent era). Caveat: wings priced with ATM-level IVs (no skew);
index call skew is steeper than single-name skew, which would cheapen the sold
index wing and haircut the OTM advantage by roughly 0.5-1%/yr; OTM spreads are
also wider in premium terms.

## Top-10 momentum calls + short SPY calls (real IVs, 2007-2026)

Best top-10 variant (6M lookback, 30-delta): Sharpe 0.51, Calmar 0.19 - half
the unfiltered 90-name book (1.05 / 0.36). 1M ranking ~0; 12-1 ~0; bottom-10
LOSERS beat every top-10 (Sharpe 0.73). Momentum winners' call IVs are already
marked up; 10 names forfeits the breadth that powers the dispersion edge.
Recommendation stands: full universe, 30-delta, matched strikes, no ranking.

## SPY bull put spread + long single-name calls (real IVs, 2007-2026)

Sell SPY ATM put / buy 25d (or 10d) put, + long 30d single-name calls:
ann +3.0% at beta 0.49, maxDD -30%, alpha t = -3.9 (significantly NEGATIVE -
worse than 0.5x SPY+cash). Skew costs ~2.8%/yr (no-skew pricing shows +5.8%):
the bought OTM put is the most overpriced option in the market. Both legs lose
together in crashes (five ~-6% months in 2008-09/2020). Structure rejected;
matched-strike call dispersion remains the only positive-alpha construction.

## Weekly put-dispersion ladder (long 6M 20d single puts 1.25x / short 3M 30d SPY puts 1x)

Real 90d/180d put IVs, weekly cohorts held to expiry, 2006-2026, skewed wings:
combo +1.14%/yr (short SPY put leg +5.3%, long single puts -4.0%); 2022 +6.5%
but COVID -7.3% and 2008 calendar -12.7% - the 3M short leg realizes crash
losses before 6M crash-entry cohorts pay (they expire into recovery).
Control: the SAME ladder with SPY 6M 20d puts as the hedge beats it on every
metric (+2.2%/yr, maxDD -8.6% vs -14.1%, GFC +9.1% vs -3.8%): single-name puts
are worse crash protection than index puts at 1.5-1.9x the IV (correlation ->1
in crashes). Note: expiry-cashflow accounting smooths vol; Sharpe/Calmar of
both overstated in absolute terms, comparison unaffected.

## Delta-hedged put ladder + overlays on SPY buy & hold

Fully delta-hedged (cohort P&L = vega x (realized - implied), booked at expiry):
combo +1.61%/yr, maxDD -4.5%, GFC +2.7% (vs -3.8% unhedged) - hedging fixes the
V-crash timing failure, and the single-name version now BEATS the SPY-only
control (+1.61 vs +1.24; 2022 +1.75 vs +0.37) because DH monetizes each name's
realized (idiosyncratic) vol rather than terminal moneyness. Caveats: vega
approximation ignores gamma path-dependence and hedging costs; absolute Sharpe
overstated.

Overlays on SPY B&H (2007-2026 monthly): SPY 10.6%/0.69 Sharpe/DD -51%;
+ 30d call dispersion overlay 13.4%/0.85; + DH ladder 12.3%/0.79; + both
15.1%/0.94/DD -48%; 50% SPY + dispersion 8.2%/0.98/DD -28%. The dispersion
overlay adds ~+2.8%/yr at ~zero extra vol (corr ~0); note SPY + short SPY
calls = index covered call, so the overlay implements as covered call + long
single-name calls (no naked shorts).

## Hedge frequency (Monte Carlo; no 20y intraday history exists in the data)

Per 6M 20d single-name option (GBM, sig=30%, 1.5bp stock half-spread):
weekly hedge: residual sd 1.01%, turnover 1.5x notional, cost 2.3bp;
daily: 0.48% / 2.8x / 4.2bp; 30-min: 0.16% / 9.1x / 13.7bp (turnover ~ sqrt(N)).
At book level (~1,300 concurrent positions) residual hedge noise diversifies to
<0.1%/yr already at weekly, while costs scale linearly: 30-min hedging of the
single-name book adds ~0.3%/yr of pure cost (~20% of the strategy's edge) to
remove noise that is already negligible. Overnight gaps/earnings (~35% of
single-name variance) are unhedgeable at any frequency - benign for the long
gamma leg, irreducible for the short. Optimum: daily or delta-band hedging for
the 50 single names; 30-minute (or band) hedging only for the short SPY leg
via ES futures at ~0.1-0.3bp where intraday reactivity is nearly free.

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

## Mixed-frequency DH ladder (singles daily-hedged, SPY leg 30-min via ES)

Daily realized vols, costs deducted (10.5bp/yr singles + 5bp SPY futures):
net +1.27%/yr, vol 0.8%, maxDD -4.1%, Calmar 0.31, beta +0.01; stable across
halves (1.31/1.24). Crisis: GFC +2.8%, COVID window +2.5%, 2022 +1.4%; long
leg alone GFC/COVID ~+6.7%. Apr-2025: net -1.25% (realized spike too brief for
6M vega, short 3M SPY leg paid the move). The big-upside tail products the
user references are NET LONG vol with far-OTM wings and no short leg - this
book deliberately sells that convexity back via the SPY leg to earn carry;
at 2x long notional crisis gains roughly double but carry drops toward zero.
Cohort-expiry accounting smooths marks; live product would see the crisis
gains earlier (mark-to-market vega repricing) and larger (vol-of-vol convexity
not modeled), which is consistent with the sharp crisis spikes seen in
comparable listed products.

## Final portfolio: 50% SPY + 50% levered dispersion sleeve (2007-2026, GS costs)

| | ann | vol | Sharpe | maxDD | beta |
|---|---|---|---|---|---|
| 100% SPY | +10.6% | 15.3% | 0.69 | -50.8% | 1.00 |
| 50/50 with 10x sleeve | +18.5% | 15.1% | 1.22 | -29.3% | 0.58 |
| 50/50 with 5x sleeve | +12.5% | 10.3% | 1.21 | -26.9% | 0.54 |

Same vol as SPY, ~+8pp/yr, half the drawdown; Sharpe plateaus at ~5x.
Sleeve at 10x: ~6%/mo premium outlay, short SPY call notional ~450% of
capital -> portfolio-margin/PB structure only. Model error scales 10x;
recommended start 3-5x with monthly leverage reset (never loss-scaled),
scale up only after live tracking confirms pricing. Worst months at 10x:
Oct08 -10.2%, Jun23 -7.8%, Mar20 -7.5%; losing years 2008 -9.0, 2022 -10.3.

### 20x sleeve variant (same 50/50 construction)

| | ann | vol | Sharpe | maxDD | beta | worst mo |
|---|---|---|---|---|---|---|
| 50/50 with 10x sleeve | +18.5% | 15.1% | 1.22 | -29.3% | 0.58 | -10.2% |
| 50/50 with 20x sleeve | +30.1% | 26.5% | 1.14 | -47.2% | 0.67 | -19.0% |
| 20x sleeve standalone | +43.6% | 49.0% | 0.89 | -83.7% | 0.34 | -44.4% |

20x: Sortino 2.32, win 62%, VaR95 -8.5%, CVaR95 -11.9%; total 155x vs SPY
6.9x (2007-2026, monthly 50/50 rebalance). Crisis flips sign vs 10x: 2008
+1.6% (sleeve +57.9% offsets SPY) but model-error months dominate instead -
worst are Jun23 -19.0%, Apr20 -15.1%, Apr21/Nov23 -13.5%; losing years 2018,
2020 (-12.2%), 2022 (-14.4%), 2023 (-10.7%). Sharpe now DECLINES with
leverage (1.22 -> 1.14) and maxDD nearly matches SPY: past 10x, leverage adds
vol faster than return. Mechanics: ~13% of total capital in premiums each
month, short SPY call notional ~900% of total capital, sleeve standalone
maxDD -84% - a single mis-modeled month at 20x is fatal in practice.
Assessment: 20x is past the efficient point; 10x was already the stretch case.

### Rebalance policy for the 50/50 portfolio (20x sleeve)

Previously reported 50/50 stats already assume MONTHLY rebalance. Comparison:
monthly +30.1%/26.5% vol/Sharpe 1.14/DD -47.2%/worst -19.0% (155x);
annual (Dec) +31.7%/27.3%/1.16/-45.4%/worst -23.7% (194x);
no rebalance +38.5%/47.2%/0.82/DD -83.2%/worst -44.2% (517x) - weights drift
to 99% sleeve (91% at 10x), i.e. the un-rebalanced portfolio degenerates into
the standalone levered sleeve. Monthly vs annual is second-order (10x: Sharpe
1.22 vs 1.24); the essential discipline is the monthly reset of sleeve
leverage to target from current equity, never loss-scaled.

### Weekly rebalance (real weekly SPY, sleeve accrual bounded two ways)

Sleeve P&L books at monthly expiries, so intra-month marks are approximated:
"smooth" spreads the month's sleeve return evenly across its weeks (understates
sleeve vol), "expiry" books it all in expiry week (overstates lumpiness); the
truth sits between. 20x sleeve, weekly grid 2007-2026:
expiry accrual - weekly reb +30.3%/Sharpe 1.12/DD -49.7% vs monthly reb
+29.9%/1.12/-49.2%; smooth accrual - weekly +27.3% vs monthly +29.9%.
10x: weekly and monthly within 0.3-0.7pp/yr on every metric.
Conclusion: weekly rebalancing is indistinguishable from monthly (differences
are within the accrual-approximation error); no evidence it adds value, and
it adds 4x the rebalancing trades. Monthly reset remains the recommendation.

### Retail vs institutional quoting for the 50/50 portfolio

All previously reported 50/50 numbers used institutional (GS) quoting
(~0.2-0.3%/yr per 1x of sleeve). Cost model: annual traded premium ~19.8%/yr
per 1x (1.27%/mo entry x ~1.3 for ITM closes/rolls) x half-spread h.
GS h~1.5% of premium -> 0.30%/yr per 1x; IBKR retail h~4% -> 0.79%;
Saxo/crossing screens h~8% -> 1.58%. Because cost scales with leverage while
vol does not, quoting venue moves Sharpe/Calmar materially:

10x sleeve: GS +17.9%/Sharpe 1.18/Calmar 0.61; IBKR +15.1%/1.00/0.50;
Saxo +10.7%/0.70/0.33. 20x: GS 1.09/0.60; IBKR 0.86/0.45; Saxo 0.51/0.21
(DD -64%). 5x: GS 1.18; IBKR 1.05; Saxo 0.84.

Feasibility dominates costs at retail anyway: short SPY call notional is
~45% of total capital per 1x of sleeve (450% at 10x, 900% at 20x). Only
L<=1.1x is fully covered by the 50% SPY holding (a covered call); beyond
that the calls are naked index shorts - IBKR portfolio margin realistically
supports ~3-5x (house stress tests bind well before 10x), Saxo effectively
none at size. Conclusion: 10-20x versions are institutional (PB) products;
the retail (IBKR) version of this strategy is the 3-5x sleeve at Sharpe
~1.0-1.05, Calmar ~0.4-0.45 - roughly 0.13-0.18 of Sharpe given away to
retail spreads plus the leverage cap.

## Retail product: liquid-30 dispersion (tenor/delta chosen for retail quoting)

Retail quoting approaches GS-like only in: SPY options (any delta, h~0.5%),
and 1M near-money options on the ~30 highest-dollar-volume mega-caps
(h~1.5-3% of premium vs 4-10% further OTM / longer tenor / smaller names).
Universe rebuilt point-in-time: top-30 by trailing-12m median dollar volume
within the SPX top-100 (hand-picked mega-cap list showed +4.3%/yr gross but
that is hindsight bias - PIT filter gives +2.97%, used throughout).

1x book, 1M 30-delta, notional-matched short SPY 30d calls (2007-2026):
PIT liquid-30 gross +2.97%/Sharpe 0.97; net retail (h=3%/0.5%, x1.3 exits
= 0.71%/yr) +2.24%/Sharpe 0.73/Calmar 0.31, halves +3.6/+2.4 - vs broad
90-name book net retail (h=6% at 30d) +1.41%/0.56. The liquid subset loses
little gross edge (mega-cap IV ratio to SPY is as rich) and saves half the
costs: at retail, liquidity selection beats breadth. 40d/ATM worse both
gross and net; top-20 noisier (0.59), top-50 dilutes into wide quotes.

RETAIL 50/50 PRODUCT (50% SPY B&H + 50% levered liquid-30 sleeve, IBKR):
| L | ann | vol | Sharpe | maxDD | beta | worst mo |
|---|---|---|---|---|---|---|
| 1x (fully covered) | +7.5% | 8.1% | 0.92 | -27.6% | 0.52 | -8.6% |
| 3x | +9.8% | 9.7% | 1.00 | -26.8% | 0.56 | -9.3% |
| 5x | +12.0% | 11.9% | 1.00 | -28.4% | 0.60 | -9.9% |
| 8x | +15.2% | 15.8% | 0.96 | -31.8% | 0.66 | -11.0% |
GS reference on same book: 5x Sharpe 1.08, 10x 1.03 - the retail penalty on
this construction is ~0.08 Sharpe (vs ~0.2 on the broad book).

Recommended retail spec: monthly cycle; long 1M 30-delta calls on top-30
dollar-volume names, ~3% notional each per 1x; short SPY 1M 30-delta calls,
notional-matched (~90% per 1x); hold to expiry; leverage reset monthly from
equity, never loss-scaled. L=1 is a covered-call-plus-calls structure with
no margin dependency (Saxo-compatible); L=3-5 needs IBKR portfolio margin
(short call notional 135-225% of capital). 5x: +12.0%/yr, Sharpe 1.00,
worst months Oct08 -9.9%, Mar20 -7.6%; losing years 2008 -13.1, 2022 -19.5,
2018 -6.4. Practical from ~$100k (1-2 contracts/name); ~60 tickets/month.

### Delta grid + cyclical SPY-only hedging of the retail liquid-30 sleeve

Daily-mark simulation, monthly cohorts 2007-2026: singles held to expiry
(never hedged individually); the BOOK's net delta (entry IVs, remaining T)
re-hedged with SPY at none/weekly/daily frequency, 1bp per unit turnover.
1x net-retail results: matched-delta pairs all improve with a WEEKLY hedge
(L20/S20: +2.57%/Sharpe 1.04/Calmar 0.56 vs 0.95/0.47 unhedged; L30/S30:
0.83 vs 0.76; L40/S40 0.54 - lower delta better throughout); daily hedging
adds cost, not Sharpe (turnover 0.6-0.8x/mo vs 0.3-0.4x weekly, ~equal
stats). Short SPY ATM leg is strongly negative in every hedge mode (-0.5 to
-3.6%/yr; ATM vega/gamma mismatch vs OTM singles) - matched strikes stay
mandatory. Hedge turnover at weekly is ~0.3x book notional/mo: ~1 SPY (or
MES) trade/week, retail-free.

RETAIL 50/50 with weekly-hedged L20/S20 sleeve (capin 0.81%/mo per 1x):
| L | ann | vol | Sharpe | Sortino | maxDD | Calmar | worst mo |
|---|---|---|---|---|---|---|---|
| 3x | +10.3% | 9.5% | 1.09 | 1.73 | -26.2% | 0.39 | -8.9% |
| 5x | +12.9% | 11.2% | 1.15 | 2.12 | -24.9% | 0.52 | -9.4% |
| 8x | +16.9% | 14.3% | 1.18 | 2.61 | -25.4% | 0.66 | -10.0% |
(L30/S30 weekly: 5x Sharpe 1.08 - 20-delta wins once the SPY hedge absorbs
the gap risk.) 5x losing years 2008 -14.9, 2022 -15.6, 2018 -2.4; worst
months Oct08 -9.4%, Jun22/Sep22 -5.4%. Beats the unhedged retail product
(Sharpe 1.00) and matches the GS unhedged reference (1.08) - the weekly
SPY hedge buys back the institutional edge at ~zero retail cost. 20-delta
spread sensitivity is small (premiums tiny: h 5->8% costs ~0.04%/yr per 1x).
Updated retail spec: long 1M 20d calls top-30 liquid names, short SPY 1M
20d calls notional-matched, weekly net-delta re-hedge with SPY/MES,
monthly reset; L=5 recommended, L=8 for the aggressive version (PM margin:
short calls 225%/360% of capital).

### Single-equity-side hedging (CFD delta hedge / call spreads) - Calmar 0.8 target

1x sleeve variants, net retail (CFD: 2bp/turn + 1%/yr financing on hedge
notional; option legs at liquid-name spreads incl. 8-10% on far-OTM wings):
| variant | ann | Sharpe | maxDD | Calmar |
|---|---|---|---|---|
| base L20/S20, wk SPY hedge | +2.57% | 1.04 | -4.6% | 0.56 |
| + singles CFD hedge weekly | +1.99% | 1.17 | -3.3% | 0.61 |
| + singles CFD hedge DAILY | +2.20% | 1.18 | -2.8% | 0.80 |
| spread L20-5/S20, wk SPY hedge | +2.84% | 1.35 | -3.7% | 0.77 |
| spread L30-10/S30, wk SPY hedge | +3.13% | 1.36 | -2.9% | 1.07 |
| spread ATM-10/SATM | +2.14% | 0.65 | -8.3% | 0.26 |
| defined-risk credit spreads both sides | <=+1.4% | <=0.76 | - | <=0.33 |

Selling the far-OTM wing per name (30-10 call spread) is the best structure:
keeps the dispersion core, sells back blowout upside that was overpaid for.
Defined-risk both-sides (SPY credit spread) destroys the short-leg edge -
rejected. ATM long leg again rejected. Caveat: wings priced at flat IV
(no smile); single-name 10d calls usually trade ABOVE ATM IV, so selling
them should collect more than modeled (conservative direction).

50/50 PORTFOLIOS reaching Calmar ~0.8 (retail, 2007-2026):
| construction | ann | vol | Sharpe | Sortino | maxDD | Calmar | beta |
|---|---|---|---|---|---|---|---|
| L20/S20 + daily CFD hedge, 10x | +17.7% | 14.0% | 1.26 | 2.24 | -21.8% | 0.81 | 0.72 |
| spread L20-5/S20 wk-hedge, 12x | +24.2% | 17.8% | 1.36 | 3.03 | -29.2% | 0.83 | 0.92 |
| spread L30-10/S30 wk-hedge, 12x | +26.0% | 18.8% | 1.38 | 2.50 | -32.3% | 0.80 | 0.94 |

Route 1 (fully hedged) is the defensive Calmar-0.8: smallest DD, 2008 NOT a
losing year (only 2018 -6.0, 2022 -12.9; worst mo Oct08 -11.5%); needs daily
per-name CFD rebalancing (~30 tickets/day automated, short CFD notional
~200% of capital at 10x). Route 2/3 (options-only spreads) hit Calmar 0.8
via return, not DD control: no CFD ops, 4 option legs/name, Sortino 3.0,
but beta ~0.9 and worst month -13 to -17%. All need portfolio margin; model
error scales with L as before.

### Max-Calmar retail hunt: regime filters rejected; SPY weight is the lever

Regime filters that switch OFF the short SPY leg (SPY drawdown >10/15%,
VIX>25/30, below 200d MA) all sharply REDUCE Calmar (L30-10/S30: 1.07
unfiltered -> 0.24-0.42 filtered): the short leg earns most in turbulent
months (rich premium) and hedges long-leg bleed; skipping 38 high-vol
months forfeits far more than the rebound-rip losses avoided. Vol-selling
exclusion makes no sense in this structure.

The real Calmar lever is the SPY allocation: SPY B&H (own Calmar 0.21)
dominates portfolio drawdown. Grid SPY weight x leverage (IBKR quoting,
Calmar shown with 1st/2nd-half split):
best structure = L30-10/S30 call spreads, weekly SPY book hedge:
| allocation | ann | vol | Sharpe | Sortino | maxDD | Calmar | halves |
|---|---|---|---|---|---|---|---|
| 100% sleeve 5x | +17.7% | 11.5% | 1.54 | 3.36 | -13.6% | 1.31 | 1.51/1.12 |
| 100% sleeve 8x | +27.8% | 18.4% | 1.51 | 3.29 | -21.4% | 1.30 | 1.56/1.06 |
| 100% sleeve 10x | +34.5% | 23.0% | 1.50 | 3.27 | -26.4% | 1.31 | 1.60/1.05 |
| 25/75 8x | +23.6% | 16.0% | 1.47 | 2.93 | -23.8% | 0.99 | 1.10/1.00 |
| 50/50 12x | +26.0% | 18.8% | 1.38 | 2.50 | -32.3% | 0.80 | 0.86/0.92 |
Calmar is FLAT in leverage (~1.3) for the pure sleeve - take the margin-
comfortable 5x. L20-5/S20 tops at ~1.0, CFD-hedged at ~0.96: the 30-10
spread book dominates. Beta at pure 5x: 0.37; worst month -7.0%.

BEST RETAIL VARIANTS (IBKR):
1. MAX CALMAR: 100% L30-10/S30 sleeve at 5x - +17.7%/yr, Sharpe 1.54,
   Sortino 3.4, maxDD -13.6%, Calmar 1.31 (both halves >1.1), beta 0.37.
   Per month: buy 30d call & sell 10d call on each of top-30 liquid names
   (4.5%xL notional each side), sell SPY 30d calls 90%xL notional, weekly
   SPY/MES net-delta hedge, monthly reset. IBKR PM comfortable at 5x.
2. AGGRESSIVE: same at 8x - +27.8%/yr, Calmar 1.30, DD -21.4%, PM tight.
3. WITH MARKET EXPOSURE: 25% SPY + 75% sleeve 8x - +23.6%/yr, Calmar 0.99.
Caveats: single-name 10d wings priced flat-IV (real call smile means selling
them collects MORE - conservative); model error scales with leverage; 2nd-half
Calmar ~1.05 is the realistic forward expectation, not 1.3.

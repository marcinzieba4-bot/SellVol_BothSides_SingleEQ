# Build prompt: Mega-cap Call Dispersion (GS institutional + tastytrade retail)

You are building, from scratch, a systematic options strategy called
**mega-cap call dispersion**. Everything below is the full specification;
do not import code from other projects. Build the backtest first, reproduce
the reference numbers, then the execution layer.

## 1. The economic idea

1-month implied vols of S&P mega-caps trade at ~1.5–1.9x SPY's implied vol,
slightly richer than the level justified by realized correlation (break-even
ratio ~1.57, median traded ~1.59, and the richness is concentrated in the
upside/call wing). The strategy is LONG single-name upside convexity and
SHORT index upside convexity, delta-matched and notional-matched, harvesting
that spread. Properties to preserve at all costs: near-zero beta (~0.1–0.4),
crisis-POSITIVE profile (2008 was the best year; losses come from single-name
dispersion droughts like 2022–23, not from crashes), no short puts anywhere.

## 2. Universe (point-in-time, monthly)

- Base: the top-100 S&P 500 members by market cap, as of each historical
  month (use historical constituent lists — no survivorship).
- Tradable set: the top-30 of those by TRAILING 12-month median daily dollar
  volume, computed with data known at month start. Dollar volume is the
  liquidity proxy that keeps retail option spreads near-institutional.
- No other selection. Momentum/winner filters were tested and SUBTRACT value;
  breadth is the engine — never run fewer than ~13 names.

## 3. Monthly cycle (month-end to month-end, all legs same ~1M expiry)

### Single-equity side (long-vol leg)
For each of the N=30 names: BUY one ~30-delta call and SELL one ~10-delta
call of the same expiry (a debit vertical). Equal notional per name
= 0.9 x L / N of account equity (L = sleeve leverage). Hold to expiry.
Do NOT delta-hedge individual names in the base product. (Institutional
option: daily per-name stock/CFD delta-hedging lowers drawdown further at
the cost of return — Calmar-equivalent, operationally heavy.)

### Index side (short-vol leg)
SELL ~30-delta index calls, total notional = 0.9 x L of equity (matched to
the long side), same expiry, hold to expiry. Three implementations:
- **GS / prime broker / portfolio margin:** naked short SPY (or SPX) calls.
- **tastytrade / any small account (DEFAULT retail):** sell ~30-delta calls
  on ES or MES FUTURES OPTIONS. SPAN margin is risk-based with no $100k
  portfolio-margin floor, so full naked-short economics at any size.
  MES (1/10 ES) while short notional < ~$300k, ES above.
- **Pure equity options under Reg-T:** SPY 30-delta/1-delta call CREDIT
  spread. The 1-delta wing is nearly free and satisfies Reg-T pairing
  (costs ~0.1 Sharpe vs naked). Never use a 5-delta-or-nearer wing.

### Strike selection
From the live chain, pick the listed strike nearest the Black-Scholes
delta target: K = S * exp(-z_d * s + s^2/2), s = IV30 * sqrt(T), with
z_30 = -0.5244, z_10 = -1.2816, z_01 = -2.3263 (calls). If the 1-delta
strike exceeds the listed chain, take the furthest listed strike.

## 4. Hedging

Once per WEEK: compute the net book delta (Black-Scholes deltas at entry
IVs, remaining time; sum over all option legs, long and short) and trade
SPY shares or MES futures to bring it to zero. Weekly is optimal: daily
doubles turnover for no Sharpe gain; never hedge intraday for singles.
Hedge turnover is ~0.3x book notional/month (one small trade a week).

## 5. Sizing, leverage, discipline

- L = 5 recommended (start at 3 live; 8 = aggressive cap). Sharpe/Calmar are
  flat in L for the pure sleeve, so L is a sizing choice, not an edge choice.
- Reset all position sizes MONTHLY from current equity. NEVER scale up after
  losses (no recovery/martingale sizing — tested, it is ruin at leverage).
- Cap projected margin usage at 60% of equity (use the broker's dry-run /
  what-if endpoint before each order).
- Small accounts (< ~$276k x L/5, from option contract granularity, 100
  shares/contract): trade a rotating 15-name HALF of the top-30 each month
  (odd liquidity ranks one month, even the next — breadth via time), and
  skip any name whose single contract exceeds 2x the per-name target
  notional. Workable from ~$50–60k. Below that, mechanics-validation only.

## 6. Costs to assume in the backtest

Half-spread as % of option premium, x1.3 to cover ITM exits/rolls:
mega-cap 1M options: 1.5% ATM, 3% at 30-delta, 8% at 10-delta, 15% at
1-delta; SPY options 0.5%; ES/MES options 0.3%; stock/futures hedge 1bp of
turnover. GS institutional: ~1.5% flat on premium (~0.3%/yr per 1x of book
vs ~0.7%/yr retail). Commissions are second-order (tastytrade $1/contract
to open, $0 to close).

## 7. Data to use

- **Option IVs (the critical input):** daily or month-end 30-day implied
  vols per name and for SPY — ORATS, OptionMetrics/IvyDB, LiveVol, or
  VolVue (`iv_call_30`, `iv_put_30` fields; values in vol points). Entry
  uses the PRIOR month-end IV. Do not proxy IVs from realized vol: trailing
  realized lags crashes and inflates backtests (~+7%/yr artifact — tested).
- **Prices:** daily adjusted closes for all names + SPY (yfinance-grade is
  fine); monthly closes derive from them.
- **Liquidity ranking:** daily (or monthly) share volume x close, trailing
  12m median, shifted one month (known at entry).
- **Historical index membership:** point-in-time S&P 500 top-100 lists.
- **Rates:** FRED FEDFUNDS (cash yield on unused equity), VIXCLS (sanity).
- **Backtest pricing:** Black-Scholes, flat IV across strikes per name.
  Know the bias: flat-IV UNDERSTATES what you collect selling single-name
  OTM call wings and OVERSTATES the cost of far index wings — both make the
  live product slightly better than the backtest, not worse.

## 8. Reference numbers to reproduce (2007–2026, net of retail costs)

1x book: gross +2.97%/yr; net +2.2–3.1%/yr, Sharpe ~0.97–1.36 depending on
structure; 30-10 verticals + naked index leg + weekly hedge is the best:
Sharpe 1.36, maxDD −2.9%, Calmar 1.07 at 1x.
Recommended product (100% sleeve at 5x, naked/SPAN index leg):
**+17.7%/yr, vol 11.5%, Sharpe 1.54, Sortino 3.4, maxDD −13.6%, Calmar 1.31,
beta 0.37, worst month −7.0%, 2008 +15%, losing years only 2011/2018/2022-ish
(≤ −8%).** Reg-T 1-delta-wing version: Sharpe 1.46–1.55, Calmar 1.19–1.28.
$100k rotating-half version: +19.6%/yr, Sharpe 1.44, Calmar 1.12.
Treat the SECOND-HALF-only Calmar (~1.0–1.1) as the realistic forward
expectation; the 2008–2012 dispersion era flatters full-sample numbers.

## 9. Tested and REJECTED — do not re-add

- Short puts, on index or singles, any size (destroys the crisis-positive
  profile: 2008 flips from +15% to −10…−29%).
- Put-side dispersion ladders; ATM short legs; strangles.
- Momentum/top-10 name selection (losers beat winners; breadth wins).
- Regime filters that switch off the short index leg in high vol / drawdown
  / below-MA states (halves Calmar: the short leg earns most then).
- Letting the portfolio drift un-rebalanced; loss-scaled ("recovery") sizing.
- Buying the index wing nearer than ~2-delta under Reg-T (5-delta wing
  costs ~0.2 Sharpe).

## 10. Execution & ops

Limit orders at mid, walked toward the far side in 3–4 steps of ~20% of the
half-spread, 15–20s apart; verticals as single 2-leg tickets; ~35 option
tickets/month + 1 hedge trade/week + monthly roll on the last trading day.
Safety rails: margin > 60% -> cut L by 1 at next roll; equity below the
broker's PM/maintenance floor + buffer -> flatten the short leg first.
Validate on the broker sandbox, then live at L=1–3 for 3+ months comparing
realized entry premiums vs model before scaling to L=5.

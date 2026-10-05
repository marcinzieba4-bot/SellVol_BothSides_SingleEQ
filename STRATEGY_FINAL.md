# SellVol single-equity put selling — final form, sizing, and what the data says

_2026-10-05. Numbers from `history.csv` / `portfolio_sell_put_1m.csv` (backtest 2015-02 → 2024-12) and
`sim_small_account.py` (same trades replayed with integer contracts, buying-power caps, commissions and slippage)._

## 1. Where the backtest return actually comes from

| | Points of return (arithmetic, % of capital) | Months |
|---|---|---|
| Months at base size (1 % of capital per name) | **11.4** | 65 |
| Months in recovery (martingale multiplier 2× … 818×) | **80.6** | 54 |
| Total | 91.9 | 119 |

Three recovery months (Jan-2019 at 16× capital notional, Jul-2022 at 7×, Oct-2022 at 4×) contribute 70 of the
92 points. Jan-2019 alone needed 327 % of capital in Reg-T buying power: no broker finances it.

The base trade (sell ATM ~30-DTE put after an up month) has almost no expectancy of its own:

| Window | Mean P&L per unit (% of notional per month) | ATM premium | 1× notional, equal-weight, compounded |
|---|---|---|---|
| 2015-02 → 2024-12 (proxy premiums before 2020-09) | +0.075 % | 2.32 % | +16.9 % over 119 months |
| 2020-09 → 2024-12 (real S3 premiums) | +0.29 % | 2.96 % | +21.9 % over 52 months |
| 2022 → 2024 | −0.09 % | 2.90 % | 0.0 % over 36 months |

Premium collected ≈ 2.3 % of spot; average loss from down-months ≈ 2.2 %. The put is priced fairly. Costs are not in
these numbers: tastytrade commission $1/contract plus half the bid-ask spread (10 % of premium ≈ 0.3 % of notional per
month) consume the whole base edge. The buy-call variants are the same story in reverse: 999 of 1,033 points come from
recovery months, with up to 74× capital deployed.

## 2. The same trades under real account constraints

`python3 sim_small_account.py` — 1 contract per name, a name is skipped when one contract's notional exceeds 25 % of
equity, buying power capped at 50 % of equity, Reg-T = 25 % of notional (measured), PM = 12 %, 10 % slippage, $1.10
commission, dollar P&L compounding:

| Scenario | Final equity | CAGR | Max DD | Names (median) | Max multiplier |
|---|---|---|---|---|---|
| $50k Reg-T, flat size, no recovery | $30k | −4.9 % | −46 % | 15 | 1 |
| $50k Reg-T, recovery capped at 50 % BP | $35k | −3.6 % | −46 % | 15 | 10 |
| $50k Reg-T, recovery capped at 80 % BP | $31k | −4.7 % | −60 % | 21 | 16 |
| $125k Reg-T, recovery capped at 50 % BP | $72k | −5.4 % | −49 % | 27 | 26 |
| $125k PM, flat size | $45k | −9.7 % | −69 % | 35 | 1 |
| $125k PM, recovery capped at 50 % BP | $43k | −10.3 % | −74 % | 33 | 35 |
| $1M PM, recovery capped at 50 % BP | $533k | −6.2 % | −66 % | 60 | 250 |
| $1M PM, 1 %-of-capital units, recovery capped | $1.30M | +2.7 % | −9 % | 29 | 252 |
| Reference: backtest, no constraints | — | ≈ +8 % | −19 % | 55 | 818 |

Why the small-account versions lose: (a) "1 contract per name" with a 50 % BP cap is 2× notional on equity, so the
near-zero base edge is levered and the costs doubled; (b) the names that fit a small account (spot ≤ $125: CMCSA, T,
PFE, BSX, VZ, BAC, NFLX, MO, UBER, NEE, WFC, KO, MDT, APH, SCHW, ABT, DIS, WMT, BX, CSCO) had a per-unit mean of
−0.01 %/month versus +0.09 % for the rest; (c) a capped martingale cannot deliver the recovery months that made the
backtest, and portfolio margin only lets the multiplier run further before the cap, which made drawdowns deeper.

## 3. What portfolio margin changes

- BP per ATM put falls from ~25 % to ~10–15 % of notional: the same capital holds about twice the contracts.
- Nothing changes in expectancy. PM is cheaper leverage, and here leverage is applied to a trade with no edge after costs.
- Needs $125k (some tastytrade pages say $175k) net-liq to activate, $100k–150k to keep. Apply at my.tastytrade.com →
  Manage → My Profile → Account Settings → Portfolio Margin.

## 4. Final form of the strategy (as it would have to be run)

1. **Universe**: current top-100 S&P 500 single names (`2026.txt`), filtered each month to names whose ATM put has a
   bid-ask spread ≤ 10 % of mid and liquidity rating ≥ 3 (from `feasibility_live.py`).
2. **Signal**: at the first trading day of the month, if the previous monthly candle closed up → sell one ATM put
   expiring in ~30 DTE (nearest monthly ≥ 21 DTE). Previous candle down → no trade in that name.
3. **Unit**: 1 % of equity in notional per name; a name is skipped when one contract exceeds that (small accounts: see §5).
4. **Recovery**: when the portfolio's episode P&L is negative, multiply all sizes by
   `ceil(deficit / expected premium) × 2`, **capped so Reg-T BP ≤ 50 % of equity** (PM: ≤ 35 %). Reset to 1× when the
   episode P&L is back to ≥ 0.
5. **Exit**: hold to expiration. If assigned, sell the shares at the next open (the backtest's cash-settled equivalent).
6. **Execution**: sell at mid, re-price toward the bid every minute for 10 minutes; skip the name if unfilled.
7. **Kill-switch**: stop trading if equity drawdown from peak exceeds 20 %.

## 5. Running it with $50k

- Reg-T, 25 % BP per contract, 50 % BP cap → $25k BP → ≈ $100k notional → 10–15 names at 1 contract each, all under
  ~$125/share. That is a different portfolio from the one that was backtested, and on the backtest data it lost
  3–5 % a year with a 46 % drawdown.
- Portfolio margin is not available at $50k.
- The honest recommendation: **do not fund this version with $50k.** Use the next 3–6 months to (1) run
  `feasibility_live.py` daily to collect real premiums, spreads and buying-power for all 100 names, (2) re-run the
  backtest with those premiums and the costs above, (3) find a base trade with positive expectancy before any sizing
  rule is layered on top. Candidates worth testing with the same engine: 30-delta instead of ATM strikes, 45 DTE
  managed at 50 % of premium, and an IV-rank ≥ 30 filter.

## 6. Take-aways

- The backtest's +92 % is a martingale artefact; the base trade earns ≈ 0 after costs.
- Capping the martingale to anything financeable removes the return; not capping it is a margin call.
- Portfolio margin halves margin per contract, it does not add edge. Apply for it only after the base trade is fixed.
- A $50k Reg-T account can hold 10–15 cheap names at 1 contract; on the backtest's own data that subset lost money.

## 7. Alternative tested: 30/10 single-name spreads + SPY 30/2 spread at 3–5×, rotating half-book, weekly share hedge

`python3 sim_spreads.py` — weekly data 2015-02 → 2024-12, Black-Scholes strikes/premiums (single-name IV from the
backtest's ATM premiums, SPY IV = VIX), 28-DTE cohorts entered every 2 weeks at half size, costs included, no
integer-contract rounding.

| Book | CAGR | Max DD | Worst 4 weeks | Feb–Apr 2020 | 2022 |
|---|---|---|---|---|---|
| A. single-name 30/10 put spreads, 1× notional | −0.7 % | −13.5 % | −4.3 % | −3.2 % | −6.1 % |
| B. SPY 30/2 put spread, 3×, unhedged | **16.4 %** | −26.4 % | −17.5 % | −14.5 % | −20.4 % |
| B. SPY 30/2 put spread, 5×, unhedged | 27.8 % | −41.2 % | −28.3 % | −24.3 % | −33.0 % |
| C. SPY 3×, weekly share hedge | 3.4 % | −15.3 % | −8.4 % | −11.8 % | −3.9 % |
| C. SPY 5×, weekly share hedge | 5.5 % | −24.8 % | −14.0 % | −19.4 % | −6.7 % |
| A + B (SPY 4× unhedged) | 20.9 % | −38.7 % | −26.7 % | −22.6 % | −31.8 % |
| A + C (SPY 4× hedged) | 3.7 % | −25.6 % | −12.5 % | −18.4 % | −11.1 % |

Per 28-day cohort, % of notional: single-name spreads −0.05 % (53 % win); SPY unhedged +0.40 % (86 % win, worst −7.3 %);
SPY hedged +0.09 % (74 % win, worst −5.4 %); entry delta of the SPY spread ≈ 0.28.

Reading: the index carries a variance-risk premium, single names do not (same result as the ATM study in §1). The
weekly share hedge gives up ~80 % of the SPY return to cut the worst drawdown by ~40 %; lowering leverage does the
same job more cheaply (3× unhedged beats 5× hedged on both return and drawdown). Caveats: model premiums with a flat
vol surface overstate the 30/2 credit (real 2-delta wings are skew-expensive, ≈ 0.1 % of notional), SPY 2015-24 is a
bull-market sample, and the single-name leg needs ~$500k before one contract per name fits.

At $50k: SPY ≈ $580 → one spread ≈ $58k notional. 4× is 3–4 spreads in total, 1–2 per cohort. The single-name leg is
not fundable at this size and adds nothing anyway.

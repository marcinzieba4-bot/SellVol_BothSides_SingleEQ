# InsideSPX Momentum — report verification

Verification of the numbers shown on the ZembiHF site
(`https://d7g7nkeytae81.cloudfront.net/strategies/` → InsideSPX Momentum, plus the
standalone page `/strategies/insidespx-momentum/`) against this repository's
simulation output (`history_buy_call_1m.csv`, `portfolio_buy_call_1m.csv`).
Run `python3 verify_report.py` to reproduce every check (needs `fedfunds.csv`,
FRED FEDFUNDS monthly series).

## What the page shows

The current revision of the `/strategies/` page presents the **uniform 1× sizing**
variant of `buy_call_1m` (no recovery scaling) and a **4× premium-outlay** variant,
with free cash earning the effective Fed Funds rate:

```
pnl_1x[m] = Σ traded pnl_pu_pct / 100                      (% of equity)
capin[m]  = Σ traded call_prem_pct / 100                   (% of equity)
r_1x[m]   = pnl_1x[m] + FFR_mo[m] · (1 − capin[m])
r_4x[m]   = 4·pnl_1x[m] + FFR_mo[m] · (1 − 4·capin[m])     (nothing borrowed)
```

All 119 monthly rows and the full summary table (totals +103.9% / +792.5%,
ann +7.5% / +24.7%, Sharpe 1.65 / 1.38, max DD −7.3% / −28.7%, …) reproduce
exactly under this reconstruction. **The numbers are right.** The problems are
labels and leftovers from the previous (2× recovery) revision:

## Errors found

1. **Stale header tiles.** The four hero tiles (+351% total, +32.8% ann, 0.63
   Sharpe, −19.9% max DD) belong to the *old 2× recovery* revision, while the
   performance table below shows the 1×/4× variant (+103.9% / +792.5%). Two
   unrelated sets of numbers on one page.
2. **The old tiles were themselves mixed-convention.** +351.3% is the
   fixed-capital (additive) total of the recovery variant, but +32.8% / 0.63 /
   −19.9% / 1.65 Calmar came from *compounding* the same series (which implies
   +1,568% total, not +351%). Consistent alternatives:
   - fixed-capital (strategy.py convention): total +351.3%, ann +35.4%,
     Sharpe 0.68, max DD −20.3 pts, Calmar 1.74;
   - compounded (plot_results.py convention): total +1,568%, ann +32.8%,
     Sharpe 0.63, max DD −19.9%, Calmar 1.65.
3. **"4× Leveraged — 3× borrowed at Fed Funds rate" is mislabeled.** The 4×
   numbers charge **no** interest on any borrowing. They are correct for a 4×
   *premium outlay from the same equity* (options embed the leverage; premiums
   average 5.1% of capital, so nothing needs to be borrowed). If 3× really were
   borrowed at FFR, the 4× column would be total +427%, ann +18.2%,
   Sharpe 1.02, max DD −30.4%.
4. **Chart doesn't match the table.** The chart (`insidespx_chart_nr.png`,
   "Pure Calls, Uniform 1× Sizing", +71%) plots the 1× P&L *without* the
   Fed-Funds cash yield, while the 1× table column includes it (+103.9%).
5. **Swapped/mislabeled table headers.** The summary-stats table carries the
   monthly table's header (`Month | 1× Ret | 4× Ret | Cap In | Bets | W/B |
   Top Pick`), while the Monthly Archive table carries the *old* recovery-page
   header (`Return | Cumul. | Bets | Wins | Win% | Top Bet | Mode`) over
   columns that actually contain 1× Ret / 4× Ret / Cap In / Bets / W/B /
   Top Pick.
6. **Stale recovery text.** The hero description ("Size doubles after a
   drawdown month…"), How-It-Works step 04 ("Portfolio-Level 2× Recovery") and
   the vestigial "Recovery" archive filter all describe the old variant; the
   Parameters table on the same page says "uniform 1× sizing".
7. **Position-count claims.** "96 concurrent options positions each month" /
   "typically 60–100 concurrent positions": actual bets per month range 2–94,
   median 60.
8. **Sharpe/Sortino risk-free convention unstated.** The 1×/4× table uses a 0%
   risk-free rate (1.65 / 1.38). Measured against FFR the Sharpes are ≈1.25 /
   1.28. The old tiles used a 4% RF. Should be labeled.
9. **Strategy-library card out of date.** The card still shows the recovery
   variant's numbers ("+35.4% Ann (Call), 0.68 Sharpe (Call), +9.3% Ann (Put),
   0.31 Sharpe (Put)") — a third set of numbers inconsistent with both the
   tiles and the table.
10. **Standalone page `/strategies/insidespx-momentum/` is the old revision**
    (recovery variant, mixed conventions, Bets column = universe size instead
    of actual bets placed), disagreeing wholesale with the `/strategies/` page.
11. Minor wording: premiums are proxied before **Sep 2020** (VIX-scaled,
    anchor 26.37), not "pre-2020"; "rank the top-100" — nothing is ranked,
    it's a binary prior-month-return filter.

## Verified numbers (compound, cash at FFR)

| Metric            | 1× sizing | 4× premium outlay |
|-------------------|-----------|-------------------|
| Total return      | +103.9%   | +792.6%           |
| Ann. return       | +7.5%     | +24.7%            |
| Ann. volatility   | 4.5%      | 18.0%             |
| Sharpe (0% RF)    | 1.65      | 1.38              |
| Sharpe (vs FFR)   | 1.25      | 1.28              |
| Sortino (0% RF)   | 3.12      | 2.57              |
| Max drawdown      | −7.3%     | −28.7%            |
| Calmar            | 1.02      | 0.86              |
| Win rate (months) | 68.9%     | 68.9%             |
| Best / worst month| +4.4% / −2.2% | +17.2% / −8.8% |
| VaR / CVaR 95%    | −1.6% / −2.0% | −7.5% / −8.4%  |
| Capital in options| 1.3% avg  | 5.1% avg          |

Window: Feb 2015 – Dec 2024, 119 months. Bets/month: 2–94, median 60.

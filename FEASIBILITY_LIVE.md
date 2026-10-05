# Live feasibility survey — TastyTrade, 2026-10-05 (NYSE open, ~09:55–10:10 ET)

`python3 feasibility_live.py --capital 1000000 --dry-run-limit 100` → `feasibility_live_2026-10-05.csv`.
Account 5WJ29543: Margin, options level No Restrictions, Reg T, net-liq $0, **$5,000 derivative BP** (pending ACH).
Quotes: 99 of 100 names (MMC returns an empty option chain at tastytrade — ticker likely changed; check the symbol).
Expiration used: 2026-11-06 (32 DTE) for 94 names, 2026-11-20 (46 DTE) for 5 names without the Nov-6 weekly.
Dry-run buying power: 98 names (HON's dry-run came back with a 422 warning wrapper; MMC no chain). **No order was placed.**

## 1. Premiums — richer than the backtest today

| | ATM put, % of spot | ATM call, % of spot |
|---|---|---|
| mean | 4.17 % | 4.44 % |
| median | 3.94 % | 4.24 % |
| min / max | 1.43 % (BRK.B) / 7.05 % (LRCX) | |

- Backtest reference (2022-24 mean over traded months): **2.99 %**. Live / backtest ratio: median **1.38×** (p10 1.03×, p90 1.88×).
- Reason: single-name IV30 median **33** (IV rank median 0.49); earnings season starts next week, which inflates 32-DTE premiums on most of the universe. Do not treat today's 3.9 % as the run-rate; the backtest's 2.9–3.0 % is the better planning number.
- SPY for comparison: ATM 32-DTE put mid 10.75 = **1.40 % of spot** (IV ≈ 17). Single names carry ~2.8× the index premium — and, per `STRATEGY_FINAL.md` §1, roughly the same realised loss, i.e. no extra edge.

## 2. Bid-ask spreads — the hidden cost the backtest ignores

| spread as % of mid | p10 | p25 | median | p75 | p90 |
|---|---|---|---|---|---|
| ATM put | 5 % | 14 % | **23 %** | 31 % | 39 % |

- Median absolute spread $2.05 on a ~$10 option. Only **13 names ≤ 10 %** and 26 ≤ 15 %.
- By tastytrade liquidity rating (median spread): rating 4 → 14 % (21 names), rating 3 → 22 % (33), rating 2 → 25 % (41), rating 1 → 27 % (4).
- Cost if you give up half the spread: median 12 % of premium ≈ **0.44 % of notional per month** — larger than the base trade's whole 2020-24 expectancy (+0.29 %/month, `STRATEGY_FINAL.md` §1). At first-minutes-of-the-open quotes this is a worst case; re-survey at 10:30–15:30 ET before concluding, but the filter "spread ≤ 10 % of mid" in the final-form rules keeps only 13–15 names (two runs 10 minutes apart).

Names passing the ≤ 10 % spread filter right now:

| ticker | spot | put % spot | spread % mid | liq | IV30 |
|---|---|---|---|---|---|
| TSLA | 375 | 5.0 | 1.9 | 4 | 46.1 |
| AVGO | 358 | 4.4 | 2.2 | 4 | 36.8 |
| META | 738 | 5.1 | 2.4 | 3 | 43.8 |
| NFLX | 67 | 5.3 | 2.8 | 4 | 48.3 |
| AMD | 631 | 6.3 | 3.0 | 3 | 52.8 |
| NVDA | 238 | 3.9 | 3.2 | 4 | 32.4 |
| ORCL | 145 | 6.2 | 3.9 | 4 | 54.7 |
| PLTR | 190 | 6.7 | 4.3 | 4 | 50.8 |
| AAPL | 335 | 2.9 | 4.6 | 4 | 26.6 |
| IBM | 221 | 4.9 | 4.7 | 3 | 45.5 |
| AMZN | 253 | 5.0 | 4.8 | 4 | 39.7 |
| NOW | 137 | 6.9 | 4.8 | 3 | 59.5 |
| MU | 1,059 | 5.7 | 6.7 | 3 | 52.8 |

## 3. Buying power — tastytrade charges 30 %, not 20 %

| BP for 1 naked ATM put, % of notional | min | p10 | median | p90 | max |
|---|---|---|---|---|---|
| measured (dry-run, 98 names) | 25 % | 30 % | **30 %** | 35 % | 60 % (MU) |

- The house requirement is **30 % of notional** for ordinary names (Reg-T minimum would be 20 %), and higher for volatile ones:

| ticker | spot | BP % notional | IV30 |
|---|---|---|---|
| MU | 1,059 | 60.1 | 52.8 |
| NOW | 137 | 49.9 | 59.5 |
| LRCX | 346 | 39.9 | 60.6 |
| TSLA | 375 | 39.9 | 46.1 |
| KLAC | 201 | 39.7 | 62.7 |
| AMAT | 539 | 35.1 | 53.9 |
| AMD | 631 | 35.0 | 52.8 |
| GEV | 983 | 34.9 | 51.5 |
| PLTR | 190 | 34.9 | 50.8 |
| ORCL | 145 | 34.9 | 54.7 |
| PANW | 407 | 34.8 | 51.6 |
| CRWD | 272 | 34.7 | 51.9 |

- One contract on each of the 98 quoted names: **$943,641 BP on $2,951,204 notional (32 %)**. `PREFLIGHT.md` §2 assumed 20 % → every buying-power figure there scales by **1.5×**: the backtest's recovery months need p90 ≈ 80 %, p99 ≈ 210 %, max ≈ 490 % of capital.
- SPY: ATM put BP = 19.9 % of notional (index names get the Reg-T minimum). A 732/680 put spread (≈ 5 % / 12 % OTM, 52 wide) quotes 2.15 credit = 4.1 % of width = 0.28 % of spot; BP = max loss = $4,986 → exactly one spread fits the current $5,000.

## 4. Capital and granularity (live prices)

- 1 %-of-capital unit: **16 / 99 names tradable at $1M**; every name needs **$11,597,850** (binding: LLY).
- With today's $5,000 BP: 32 names have a single-put BP ≤ $5,000 (spot ≤ ~$163); all of them are in the low-priced subset that lost money in `sim_small_account.py`.

## 5. What changes versus the offline conclusions

1. **Costs are worse than assumed**: half-spread ≈ 0.4–0.5 % of notional per month on the median name vs. the 0.3 % used in `STRATEGY_FINAL.md`; only ~15 names are liquid enough for a 10 % spread filter.
2. **Margin is 1.5× worse than assumed**: 30 % (35–60 % on high-IV names) instead of 20 %. The "1 contract per name" book needs ≈ $0.95M BP, so ≈ $1.9M equity at a 50 % BP cap, not $1.2M.
3. **Premiums are temporarily rich (1.38× backtest)** because of pre-earnings IV; this is not an edge, it is the market pricing the earnings gap.
4. **Portfolio margin** would bring the 30 % back toward 10–15 %; it remains the only way the single-name book is financeable, and it needs $125k+ net-liq.
5. **SPY spreads are the only part that fits the account today**: one 52-wide 5 %/12 % OTM spread for 0.28 % of spot credit per 32 days. The `sim_spreads.py` SPY cohort return (+0.40 % of notional net) looks optimistic against a 0.28 % gross credit — re-run that sim with the live credit before sizing it.

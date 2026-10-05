# Pre-flight run

**UTC timestamp:** 2026-10-05T08:55:51Z (NYSE closed; pre-market Monday, opens 13:30 UTC)

Result: **✔ PRE-FLIGHT PASSED** (exit code 0). API access is unblocked.

## What was checked

| Check | Result |
|---|---|
| `TT_LOGIN` | set, 36 chars, UUID → OAuth client id ✔ |
| `TT_PASSWORD` (regenerated) | set, 40-char hex → OAuth client secret ✔ |
| `TT_REFRESH` (regenerated) | set, 557-char JWT (`eyJ…`, two dots) → real refresh token ✔ |
| `POST /oauth/token` grant_type=refresh_token (prod) | 200, access token issued ✔ |
| Customer / accounts | 1 account, Individual, **Margin** ✔ |
| Options level | **No Restrictions** (= "The Works"); naked puts/calls allowed ✔ |
| Margin calc | Reg T; portfolio margin **not** enabled; not in margin call |
| Balances | net-liq **$0**, cash **$0**, **pending_cash $5,000** (ACH in transit) → derivative BP $5,000, equity BP $10,000 |
| Market sessions | NYSE status=Closed, open 13:30 UTC, close 20:00 UTC ✔ |
| Equity quote | AAPL mark 333.03, bid 332.82 / ask 333.10 (Friday close data) ✔ |
| Market metrics | AAPL IV30 = 26.6, IV rank = 0.45, liquidity rating 4 ✔ |
| Option chain + quotes | AAPL 2026-11-06 (33 DTE) 335 strike: put mid 10.65 (**3.20 % of spot**), call mid 10.43 (3.13 %) ✔ |
| Dry-run SELL 1 naked ATM put | BP effect **−$8,376 = 25.2 % of $33,303 notional**; isolated margin req $9,440; current BP $5,000 ✔ |

No order was placed; the dry-run only asked the API for the buying-power effect.

## Fix made in this run

- `feasibility_offline.py` / `feasibility_live.py`: backtest reference premium now averages traded
  months only (skip months have `prem_pct = 0` and dragged the mean from 2.90 % to 1.58 %).
- `preflight.py` / `feasibility_live.py`: the SDK 13.x `MarketSession` model exposes the API's
  `state` field as `.status`; the scripts read `.state` and raised `AttributeError`. Fixed.

## Conclusions

1. **Credentials are correct now.** Keep `TT_LOGIN` / `TT_PASSWORD` / `TT_REFRESH` as they are.
   Regenerating the secret again invalidates the grant and would need a new **Create Grant**.
2. **Account permissions are sufficient** for the strategy (Margin + No Restrictions), but the
   account shows a **$5,000 ACH deposit in transit** (`pending_cash`); tastytrade grants that
   amount as instant buying power. One ATM AAPL put needs $8,376 BP > $5,000, so nothing in the
   100-name universe above ~$200/share is tradable yet. Portfolio margin (≥ $125k) is off.
3. **Margin per contract is heavier than the offline model assumed.** One ATM AAPL put consumes
   25 % of notional in Reg-T buying power versus the 20 % used in `PREFLIGHT.md` §2. Scale the
   offline buying-power figures up by ~1.25× until `feasibility_live.py` measures all 100 names.
4. **Premium matches the backtest.** AAPL ATM 33-DTE put mid is 3.2 % of spot. The backtest's
   2022-24 ATM premium on *traded* months is **2.90 % mean** (AAPL 2.84 %, Oct-2024 3.29 %).
   The "1.58 %" quoted earlier was wrong: `feasibility_offline.py` averaged over skip months,
   which carry `prem_pct = 0` (45 % of 2022+ rows). Both feasibility scripts now exclude them.
   One name, Friday-close quotes, IV30 26.6 (IV rank 0.45); the market-hours survey covers the rest.
5. **Next step:** run `python3 feasibility_live.py` between 13:30 and 20:00 UTC on a trading day
   for the 100-name premium / spread / buying-power survey.

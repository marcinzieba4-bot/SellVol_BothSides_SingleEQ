# Pre-flight: trading the SellVol strategy at TastyTrade

_Last run: 2026-10-05 04:30 ET (pre-market)._ Re-run with `python3 preflight.py`.

## 1. API access — BLOCKED on one missing value

| Item | Status |
|---|---|
| `TT_LOGIN` | is an OAuth **client id** (UUID), not a username |
| `TT_PASSWORD` | is an OAuth **client secret** (40-char hex), not a password |
| `TT_REFRESH` (refresh token) | **missing** — nothing can log in without it |
| Legacy `/sessions` login | returns `401 invalid_credentials`; tastytrade decommissioned username/password sessions on 2026-02-11 |
| `api.tastyworks.com` reachability | OK from this environment |

**Fix (account owner, ~2 min):** my.tastytrade.com → Manage → My Profile → API → OAuth Applications → open the app whose Client ID matches `TT_LOGIN` → **Create Grant** → copy the refresh token → save it as environment variable `TT_REFRESH`. Then `python3 preflight.py` runs the full check (account, options level, buying power, option chain, dry-run naked put) and `python3 feasibility_live.py` runs the market-hours check.

## 2. Offline feasibility — the sizing rule does not survive contact with contracts

Backtest unit: **1 unit = 1 % of capital in notional on each name**. The smallest tradable unit is one contract = 100 shares. A name is tradable at size 1 only if capital ≥ 10,000 × spot. With the 2026 top-100 universe at 2026-10-02 closes (`feasibility_offline.csv`):

| Capital | Names tradable at size 1 (of 99) |
|---|---|
| $250k | 2 |
| $1M | 16 |
| $2M | 43 |
| $5M | 82 |
| $11.4M | 99 (LLY at $1,143 is the binding name) |

- One contract on every name = **$2.98M notional**, ≈ **$0.6M Reg-T buying power** (20 % ATM rule). That is the real minimum "size 1" portfolio.
- The recovery sizing in the backtest (`uniform_size` × 2) runs **above 1 in 54 of 119 months**, deploys **p90 2.7×, p99 7×, max 16× capital** in notional. Reg-T buying power need: p90 55 %, p99 139 %, **max 327 % of capital** → 3 months are not financeable at all, 14 months use more than half the account on margin alone. The Jan-2019 month (uniform_size 818 on 2 names) is a backtest artefact that no broker would allow.
- Backtest premium assumption: **1.58 % of spot per month** (ATM, 30 DTE, 2022-24 mean). Live check will measure this; the backtest uses mid prices with no spread, commissions ($1/contract at tastytrade) or assignment costs.

## 3. What the market-hours check will measure (`feasibility_live.py`)

For all 100 names: ATM ~30 DTE put and call mid, bid-ask spread, premium % vs backtest, IV30 / IV rank / liquidity rating, and the **actual tastytrade buying-power effect** of selling one naked ATM put (dry-run, nothing is placed). Output: `feasibility_live_<date>.csv` plus a summary.

## 4. Conclusions so far (before live data)

1. **Feasible only as a scaled-down variant**: with less than ~$3M, trade a subset of lower-priced names (or use "1 contract per name" as the unit instead of "1 % of capital").
2. **The martingale recovery multiplier must be capped** (≈ 2–3× notional, i.e. ≤ 50–60 % of capital in Reg-T buying power) or the account hits a margin call in the tail months the backtest counts as its best recoveries.
3. **Naked puts need a Margin account with "The Works" options level**; portfolio margin (≥ $125k net-liq at tastytrade) would cut buying power roughly in half versus Reg-T and is the realistic way to run this.

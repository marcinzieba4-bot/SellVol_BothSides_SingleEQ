# Pre-flight: trading the SellVol strategy at TastyTrade

_Last run: 2026-10-05 08:55 UTC — **PASSED**, see `PREFLIGHT_RUN.md`. Re-run with `python3 preflight.py` (deps: `pip install -r requirements.txt`)._

## 1. API access — OK (2026-10-05)

| Item | Status |
|---|---|
| `TT_LOGIN` | OAuth **client id** (UUID) ✔ |
| `TT_PASSWORD` | OAuth **client secret** (40-char hex) ✔ |
| `TT_REFRESH` | refresh token (JWT from **Create Grant**) ✔ — token exchange returns 200 |
| Account | Individual, **Margin**, options level **No Restrictions** → naked puts/calls allowed ✔ |
| Margin type | Reg T; portfolio margin not enabled |
| Funding | net-liq $0, cash $0, **$5,000 ACH pending** → $5,000 derivative BP (instant-deposit credit); too small for any ATM put on a name above ~$200/share |
| Market data | equity quote, market metrics (IV30 / IV rank / liquidity), nested option chain, option quotes all OK |
| Dry-run naked ATM put | works; AAPL: BP effect = **25.2 % of notional** (vs 20 % assumed below) |

Full check: `python3 preflight.py` (account, options level, buying power, option chain, dry-run naked put).
Market-hours check: `python3 feasibility_live.py` (NYSE 13:30–20:00 UTC).

## 2. Offline feasibility — the sizing rule does not survive contact with contracts

Backtest unit: **1 unit = 1 % of capital in notional on each name**. The smallest tradable unit is one contract = 100 shares. A name is tradable at size 1 only if capital ≥ 10,000 × spot. With the 2026 top-100 universe at 2026-10-02 closes (`feasibility_offline.csv`):

| Capital | Names tradable at size 1 (of 99) |
|---|---|
| $250k | 2 |
| $1M | 16 |
| $2M | 43 |
| $5M | 82 |
| $11.4M | 99 (LLY at $1,143 is the binding name) |

- One contract on every name = **$2.98M notional**, ≈ **$0.6M Reg-T buying power** (20 % ATM rule; the live dry-run on AAPL measured **25 %**, so expect ≈ $0.75M). That is the real minimum "size 1" portfolio.
- The recovery sizing in the backtest (`uniform_size` × 2) runs **above 1 in 54 of 119 months**, deploys **p90 2.7×, p99 7×, max 16× capital** in notional. Reg-T buying power need: p90 55 %, p99 139 %, **max 327 % of capital** → 3 months are not financeable at all, 14 months use more than half the account on margin alone. The Jan-2019 month (uniform_size 818 on 2 names) is a backtest artefact that no broker would allow.
- Backtest premium: **2.90 % of spot per traded month** (ATM, 30 DTE, 2022-24 mean over months with a trade; the earlier 1.58 % figure averaged in skip months at 0 %). First live sample (AAPL, 33 DTE, Friday close, IV30 26.6): **3.2 %** put / 3.1 % call — consistent. The market-hours check will measure all 100 names; the backtest uses mid prices with no spread, commissions ($1/contract at tastytrade) or assignment costs.

## 3. What the market-hours check will measure (`feasibility_live.py`)

For all 100 names: ATM ~30 DTE put and call mid, bid-ask spread, premium % vs backtest, IV30 / IV rank / liquidity rating, and the **actual tastytrade buying-power effect** of selling one naked ATM put (dry-run, nothing is placed). Output: `feasibility_live_<date>.csv` plus a summary.

## 4. Conclusions so far (before live data)

1. **Feasible only as a scaled-down variant**: with less than ~$3M, trade a subset of lower-priced names (or use "1 contract per name" as the unit instead of "1 % of capital").
2. **The martingale recovery multiplier must be capped** (≈ 2–3× notional, i.e. ≤ 50–60 % of capital in Reg-T buying power) or the account hits a margin call in the tail months the backtest counts as its best recoveries.
3. **Naked puts need a Margin account with "The Works" options level**; portfolio margin (≥ $125k net-liq at tastytrade) would cut buying power roughly in half versus Reg-T and is the realistic way to run this.

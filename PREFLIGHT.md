# Pre-flight: trading the SellVol strategy at TastyTrade

_Last run: 2026-10-05 13:52 UTC (NYSE open) — **PASSED**, see `PREFLIGHT_RUN.md`; 100-name live survey in `FEASIBILITY_LIVE.md`. Re-run with `python3 preflight.py` (deps: `pip install -r requirements.txt`)._

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
| Dry-run naked ATM put | works; AAPL **25 %**, universe median **30 %** of notional, 35–60 % on high-IV names (vs 20 % assumed below) |

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

## 3. Market-hours check (`feasibility_live.py`) — DONE 2026-10-05, see `FEASIBILITY_LIVE.md`

For all 100 names: ATM ~30 DTE put and call mid, bid-ask spread, premium % vs backtest, IV30 / IV rank / liquidity rating, and the **actual tastytrade buying-power effect** of selling one naked ATM put (dry-run, nothing is placed). Output: `feasibility_live_<date>.csv` plus a summary.

## 4. Conclusions after the live survey (2026-10-05, 99 names, NYSE open)

1. **Feasible only as a scaled-down variant**: with less than ~$3M notional capacity, trade a subset of lower-priced names (or use "1 contract per name" as the unit). Live prices: $1M funds 16 of 99 names at a 1 % unit; every name needs $11.6M.
2. **Margin is 1.5× the offline assumption.** tastytrade's house requirement for a naked ATM put is **30 % of notional** (35–60 % on TSLA, MU, NOW, LRCX, KLAC, AMD, AMAT, GEV, PANW, CRWD, PLTR, ORCL). One contract on every name = $0.94M BP on $2.95M notional. Scale every BP figure in §2 by 1.5×: the backtest's recovery months need ≈ 80 % of capital at p90 and ≈ 490 % at the max.
3. **The martingale recovery multiplier must be capped** (≤ 50 % of equity in BP ≈ 1.7× notional at 30 %), or the account is in a margin call in the months the backtest counts as its best.
4. **Spreads kill the base edge.** Median ATM bid-ask = 23 % of mid (only 13–15 names ≤ 10 %); giving up half the spread costs ≈ 0.45 % of notional per month, more than the base trade's +0.29 %/month expectancy. Re-survey mid-session before finalising, but a 10 % spread filter leaves 13–15 names.
5. **Premiums are rich today (median 3.9 % vs 3.0 % backtest, 1.38×)** because IV30 is ~33 ahead of earnings; plan with the backtest number, not today's.
6. **Account**: Margin + No Restrictions is sufficient; portfolio margin (≥ $125k) is the only route to financing the single-name book. With the current $5,000 BP exactly one SPY 5 %/12 % OTM put spread (0.28 % of spot credit, $4,986 max loss) fits; no single-name position worth having does.

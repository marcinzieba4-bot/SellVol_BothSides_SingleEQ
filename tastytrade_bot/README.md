# Dispersion bot for tastytrade (L30-10/S30 + weekly SPY hedge)

Implements the retail dispersion product from CRITICAL_ANALYSIS.md on the
tastytrade Open API. Three scheduled jobs, one config file, no UI.

## Strategy recap

Monthly cycle (calendar month-end to month-end):
1. Universe: top-30 SPX top-100 names by trailing-12m median dollar volume
   (rotating 15-name half + granularity cutoff for accounts < ~$276k x L/5).
2. Long leg: per name, buy 1M ~30-delta call / sell ~10-delta call
   (vertical), equal notional = 0.9 x L / N per name.
3. Short leg, three modes (config short_leg):
   - es_span (DEFAULT, any account size): sell ~30-delta calls on ES/MES
     futures options in the futures side of the account. SPAN margin is
     risk-based with NO $100k/$125k floor -> full naked-short economics
     (Sharpe ~1.54): MES below ~$300k notional need, ES above.
   - spy_naked: SPY calls naked - needs PM ($125k+).
   - spy_regt: SPY 30-delta/1-delta credit spread - pure equity options,
     Reg-T at any size; the 1-delta wing costs almost nothing
     (3x: Sharpe 1.55/Calmar 1.28; 5x: 1.46/1.19).
4. Weekly: re-hedge net book delta with SPY shares (or MES elsewhere).
5. Month-end: let expire / close ITM legs, reset leverage from equity,
   rebuild the book. NEVER scale up after losses.

## Jobs (cron)

| job        | schedule                | what it does                        |
|------------|-------------------------|-------------------------------------|
| roll.py    | last trading day, 15:30 ET | close expiring book, size + open new cohort |
| hedge.py   | Mondays 10:00 ET        | net delta -> SPY share order        |
| monitor.py | daily 16:30 ET          | equity vs PM floor, margin usage, kill-switch |

## tastytrade API surface used

- `POST /sessions` (or OAuth2) - auth; sandbox at `api.cert.tastyworks.com`
- `GET /option-chains/{sym}/nested` - expirations + strikes + streamer syms
- `GET /api-quote-tokens` + DXLink websocket - Quote/Greeks events (delta
  per strike; mid prices)
- `POST /accounts/{id}/orders/dry-run` - buying-power effect BEFORE placing
  (the margin pre-check; abort if projected usage > cap)
- `POST /accounts/{id}/orders` - multi-leg limit orders (verticals in one
  ticket), equity orders for the hedge
- `GET /accounts/{id}/positions`, `/balances` - state for sizing and hedge

## Execution policy

- All option orders: LIMIT at mid, repriced toward the far side in 3 steps
  of 20% of the half-spread every 20s; unfilled remainder cancelled and
  retried next minute; never market orders.
- Verticals placed as single 2-leg tickets (one fill, one commission cap).
- SPY hedge: marketable limit (mid +/- 1 cent).
- Order budget/month: 30 verticals + 1-6 SPY option tickets + ~5 hedges.

## Safety rails (monitor.py)

- equity < $135k (PM) -> deleverage next roll; < $110k -> flatten short leg
  (PM revokes at $100k EOD - never get there).
- margin usage > 60% of equity -> reduce L by 1 at next roll.
- any naked short leg without its paired long book -> alert + close.
- config change of L only takes effect at the monthly roll (no intra-month
  leverage changes, by design).

## Config (config.yaml)

leverage: 5            # sleeve leverage L
short_leg: es_span     # es_span | spy_naked | spy_regt
rotation: auto         # auto: on when equity < 276000 * L / 5
underlying_hedge: MES  # tastytrade has CME micros; SPY shares also fine
deltas: {long: 0.30, wing: 0.10, spy_short: 0.30, spy_wing: 0.02}
max_margin_frac: 0.60
sandbox: true

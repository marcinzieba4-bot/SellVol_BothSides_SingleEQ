# Pre-flight run

**UTC timestamp:** 2026-10-05T08:49:40Z

Result: **BLOCKED — `TT_REFRESH` holds the client secret, not a refresh token** (exit code 2).

## What was checked

| Check | Result |
|---|---|
| `TT_LOGIN` | set, 36 chars, UUID → OAuth client id ✔ |
| `TT_PASSWORD` (regenerated) | set, 40-char hex → OAuth client secret ✔ |
| `TT_REFRESH` (regenerated) | set, 40-char hex, **byte-for-byte identical to `TT_PASSWORD`** ✖ |
| `api.tastyworks.com` reachability | OK |
| `POST /oauth/token` grant_type=refresh_token (prod) | 400 `invalid_grant` — `Invalid JWT` |
| same with secret and refresh swapped (prod) | 400 `invalid_grant` — `Invalid JWT` |
| same two calls against `api.cert.tastyworks.com` (sandbox) | 400 `invalid_grant` — `Invalid JWT` |
| `tastytrade` SDK 13.2.3, pandas, requests | installed |

No order (dry-run or otherwise) was placed; the script stops before any authenticated call.

## Diagnosis

The value saved as `TT_REFRESH` is the OAuth **client secret** (the 40-char hex string that
"Regenerate Secret" produces), pasted a second time. tastytrade's token endpoint rejects it as
`Invalid JWT` because a real refresh token is a JWT: it starts with `eyJ`, contains two dots, and is
several hundred characters long. Regenerating the secret again will not help; the secret is fine.

## Next step (account owner, ~2 min)

my.tastytrade.com → Manage → My Profile → API → OAuth Applications → open the app whose Client ID
equals `TT_LOGIN` → **Create Grant** (not "Regenerate Secret") → copy the long `eyJ…` token → save it
as `TT_REFRESH`. Leave `TT_LOGIN` and `TT_PASSWORD` as they are. Start a new session and run
`python3 preflight.py`; it then performs the full check (accounts, options level, buying power,
option chain, dry-run naked put).

Note: if the secret is regenerated again later, every existing grant is invalidated and a new
**Create Grant** is needed as well.

## Fixes made in this run

- `tt_common.py`: the credential diagnosis now names this exact mistake (`TT_REFRESH` equal to the
  client secret, or any 40-char hex value) instead of the generic "not JWT-shaped"; new helper
  `refresh_token_usable()`.
- `preflight.py` / `feasibility_live.py`: stop before the SDK import and token exchange when the
  refresh token is obviously a client secret, and say why.
- Unblock instructions now state what a refresh token looks like and that it comes from
  **Create Grant**, not **Regenerate Secret**.

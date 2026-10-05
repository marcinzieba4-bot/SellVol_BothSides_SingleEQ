# Pre-flight run

**UTC timestamp:** 2026-10-05T08:46:02Z

Result: **BLOCKED — `TT_REFRESH` still missing** (exit code 2). The regenerated `TT_PASSWORD` is valid in shape but cannot log in by itself.

## What was checked

| Check | Result |
|---|---|
| `TT_LOGIN` | set, 36 chars, UUID → OAuth client id ✔ |
| `TT_PASSWORD` (regenerated) | set, 40-char hex → OAuth client secret ✔ |
| `TT_REFRESH` / `TT_CLIENT_ID` / `TT_CLIENT_SECRET` / `TT_SECRET` | unset |
| `api.tastyworks.com` reachability | OK |
| `POST /oauth/token` grant_type=client_credentials | 400 `unsupported_grant_type` |
| `POST /oauth/token` grant_type=password | 400 `unsupported_grant_type` |
| Legacy `POST /sessions` with login/password | 401 `invalid_credentials` |
| `tastytrade` SDK | was not installed; now `pip install -r requirements.txt` (13.2.3) |

No order (dry-run or otherwise) was placed; the script stops before any authenticated call.

## Conclusion

tastytrade's token endpoint accepts **only** `grant_type=refresh_token`. A client id + client secret
alone can never produce an access token, however many times the secret is regenerated. The one
missing input is the refresh token from **Create Grant** on the OAuth application.

## Next step

my.tastytrade.com → Manage → My Profile → API → OAuth Applications → open the app whose Client ID
equals `TT_LOGIN` → **Create Grant** → copy the refresh token → add it to the environment secrets as
`TT_REFRESH`. Start a new session and run `python3 preflight.py`; it then performs the full check
(accounts, options level, buying power, option chain, dry-run naked put).

## Fixes made in this run

- `preflight.py` / `feasibility_live.py`: the SDK is imported only after the credential check, so the
  credential diagnosis prints even when `tastytrade` is not installed (previously: `ModuleNotFoundError`).
- Added `requirements.txt` (requests, tastytrade, pandas).

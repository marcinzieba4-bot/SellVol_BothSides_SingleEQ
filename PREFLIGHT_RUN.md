# Pre-flight run

**UTC timestamp:** 2026-10-05T08:36:08Z

TT_REFRESH not visible in fresh session

## Details

- `env | grep -c '^TT_REFRESH='` printed `0` in a freshly started container.
- Only `TT_LOGIN` and `TT_PASSWORD` are defined, and both are empty strings.
- No `TT_CLIENT_ID`, `TT_CLIENT_SECRET`, `TT_SECRET` or `TT_REFRESH` variable is set.
- `preflight.py` was therefore not run; no API call was made and no order (dry-run or otherwise) was placed.

## Next step

Add `TT_REFRESH` (the refresh token from TastyTrade "Create Grant") and the client id/secret
to the Claude Code environment's secrets, then start a new session and re-run
`python3 preflight.py`. See PREFLIGHT.md for the full setup steps.

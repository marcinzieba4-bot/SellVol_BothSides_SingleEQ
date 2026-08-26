# Fixed InsideSPX Momentum report pages

Corrected versions of the ZembiHF site pages, ready to upload to
`s3://s3bucketmz` (all numbers verified against this repo's simulation —
see ../REPORT_VERIFICATION.md and ../verify_report.py):

| file | S3 destination |
|------|----------------|
| `strategies_index.html` | `veerock-site/static/strategies/index.html` |
| `insidespx-momentum_index.html` | `veerock-site/static/strategies/insidespx-momentum/index.html` |
| `insidespx_chart_nr.png` | `veerock-site/static/strategies/insidespx-momentum/insidespx_chart_nr.png` |

Deploy (back up the current objects first if desired):

```bash
aws s3 cp report_fix/strategies_index.html          s3://s3bucketmz/veerock-site/static/strategies/index.html --content-type text/html
aws s3 cp report_fix/insidespx-momentum_index.html  s3://s3bucketmz/veerock-site/static/strategies/insidespx-momentum/index.html --content-type text/html
aws s3 cp report_fix/insidespx_chart_nr.png         s3://s3bucketmz/veerock-site/static/strategies/insidespx-momentum/insidespx_chart_nr.png --content-type image/png
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/strategies/*"
```

## What was fixed

- Hero tiles now show the verified 1× numbers (+103.9% total, +7.5% ann,
  1.65 Sharpe at 0% RF, −7.3% max DD) instead of the stale 2×-recovery
  tiles (+351% / +32.8% / 0.63 / −19.9%), which also mixed additive and
  compounded conventions.
- "4× Leveraged — 3× borrowed at Fed Funds rate" relabeled to
  "4× Premium Outlay — options-embedded leverage, nothing borrowed"
  (the published numbers charge no interest; they are correct for a 4×
  premium outlay, wrong for actual borrowing, which would give
  +427% / +18.2% ann / Sharpe 1.02 / max DD −30.4%).
- Summary-stats and Monthly-Archive table headers un-swapped
  (archive columns are Month | 1× Ret | 4× Ret | Cap In | Bets | W/B | Top Pick).
- Sharpe/Sortino labeled with their 0% RF convention; footnote adds
  Sharpe vs FFR (1.25 / 1.28).
- Chart regenerated to include the Fed-Funds cash yield so it matches the
  table (+103.9% / +792.6%), with both 1× and 4× curves and drawdowns.
- Recovery-era text removed (hero description, How-It-Works step 04,
  vestigial "Recovery" filter); position-count claims corrected
  (2–94 bets/month, median 60); premium proxy cutoff stated as Sep 2020.
- Strategy-library card updated from the old Call/Put recovery numbers to
  the 1×/4× numbers; standalone detail page rebuilt to match the
  /strategies/ page.
